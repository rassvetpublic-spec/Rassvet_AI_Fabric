"""Транзакционное состояние задач; не использует код OMX или Superpowers."""
from __future__ import annotations

__version__ = "1.0.0"

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class FabricError(Exception):
    """Ошибка с сообщением для оператора."""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def checksum(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


PROVIDERS = frozenset({"mock", "codex-mock", "antigravity", "codex-app"})
TERMINAL = frozenset({"COMPLETE", "FAILED", "BLOCKED", "CANCELLED"})


class FabricStore:
    def __init__(self, db_path: str | Path, *, initialize: bool = False):
        self.path = Path(db_path).expanduser().resolve()
        if initialize:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file() and not initialize:
            raise FabricError(f"База состояния отсутствует; создайте её явной командой: {self.path}")
        self.db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        if initialize:
            self.db.execute("PRAGMA journal_mode=WAL")
            self._init_schema()
        elif not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone():
            self.close()
            raise FabricError("Выбранная БД не является хранилищем Rassvet AI Fabric")

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "FabricStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _init_schema(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY,
          objective TEXT NOT NULL,
          provider TEXT NOT NULL,
          workspace TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','COMPLETE','FAILED','BLOCKED','CANCELLED')),
          lease_owner TEXT,
          lease_hash TEXT,
          lease_epoch INTEGER NOT NULL DEFAULT 0,
          lease_deadline REAL,
          attempt INTEGER NOT NULL DEFAULT 0,
          cancel_requested INTEGER NOT NULL DEFAULT 0,
          result_json TEXT,
          error TEXT,
          external_run_id TEXT,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dependencies (
          task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
          depends_on TEXT NOT NULL REFERENCES tasks(id),
          PRIMARY KEY(task_id, depends_on)
        );
        CREATE TABLE IF NOT EXISTS events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL REFERENCES tasks(id),
          timestamp REAL NOT NULL,
          type TEXT NOT NULL,
          payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, seq);
        CREATE TABLE IF NOT EXISTS checkpoints (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL REFERENCES tasks(id),
          timestamp REAL NOT NULL,
          stage TEXT NOT NULL,
          verdict TEXT NOT NULL CHECK(verdict IN ('PASS','PARTIAL','BLOCKED')),
          cursor TEXT NOT NULL,
          evidence TEXT NOT NULL,
          content_sha256 TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_checkpoints_task ON checkpoints(task_id, seq DESC);
        CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(status, created_at);
        """)
        self.db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES ('schema_version','1')")

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _event(self, task_id: str, kind: str, data: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO events(task_id,timestamp,type,payload) VALUES(?,?,?,?)",
            (task_id, time.time(), kind, canonical(data)),
        )

    def _checkpoint(self, task_id: str, stage: str, verdict: str, cursor: str,
                    evidence: dict[str, Any]) -> dict[str, Any]:
        if verdict not in {"PASS", "PARTIAL", "BLOCKED"}:
            raise FabricError("Недопустимый статус проверки чекпойнта")
        if not stage or not cursor or len(cursor) > 512:
            raise FabricError("Для чекпойнта обязательны этап и курсор")
        created = time.time()
        payload = {"task_id": task_id, "timestamp": created, "stage": stage,
                   "verdict": verdict, "cursor": cursor, "evidence": evidence}
        digest = checksum(payload)
        self.db.execute(
            "INSERT INTO checkpoints(task_id,timestamp,stage,verdict,cursor,evidence,content_sha256) "
            "VALUES(?,?,?,?,?,?,?)",
            (task_id, created, stage, verdict, cursor, canonical(evidence), digest),
        )
        self._event(task_id, "CHECKPOINT", {"stage": stage, "verdict": verdict,
                                            "cursor": cursor, "sha256": digest})
        return {**payload, "sha256": digest}

    @staticmethod
    def _view(row: sqlite3.Row) -> dict[str, Any]:
        # Не раскрываем хеш аренды и данные авторизации через просмотр статуса.
        return {k: row[k] for k in (
            "id", "objective", "provider", "workspace", "status", "lease_owner",
            "lease_epoch", "lease_deadline", "attempt", "cancel_requested",
            "external_run_id", "created_at", "updated_at")}

    def submit(self, objective: str, provider: str, workspace: str,
               *, task_id: str | None = None, depends_on: list[str] | None = None) -> dict[str, Any]:
        objective = objective.strip()
        if not objective or len(objective) > 20000:
            raise FabricError("Описание задачи должно содержать от 1 до 20000 символов")
        if provider not in PROVIDERS:
            raise FabricError(f"Исполнитель должен быть одним из: {', '.join(sorted(PROVIDERS))}")
        project = Path(workspace).expanduser().resolve(strict=True)
        if not project.is_dir():
            raise FabricError("Рабочий каталог должен существовать")
        deps = sorted(set(depends_on or []))
        task_id = task_id or f"rf-{uuid.uuid4().hex[:16]}"
        if not task_id or len(task_id) > 128 or not all(c.isalnum() or c in "-_" for c in task_id):
            raise FabricError("Некорректный идентификатор задачи")
        if task_id in deps:
            raise FabricError("Задача не может зависеть от самой себя")
        with self.atomic():
            old = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if old:
                old_deps = [r[0] for r in self.db.execute(
                    "SELECT depends_on FROM dependencies WHERE task_id=? ORDER BY depends_on", (task_id,))]
                if ((old["objective"], old["provider"], old["workspace"], old_deps)
                        != (objective, provider, str(project), deps)):
                    raise FabricError("Задача с таким идентификатором уже существует, но её содержимое отличается")
                return self._view(old)
            for dep in deps:
                dependency = self.db.execute("SELECT provider FROM tasks WHERE id=?", (dep,)).fetchone()
                if not dependency:
                    raise FabricError(f"Неизвестная зависимость: {dep}")
                if provider not in {"mock", "codex-mock"} and dependency["provider"] in {"mock", "codex-mock"}:
                    raise FabricError("Реальная задача не может зависеть от имитации вместо проверки")
            now = time.time()
            self.db.execute(
                "INSERT INTO tasks(id,objective,provider,workspace,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)", (task_id, objective, provider, str(project), "QUEUED", now, now),
            )
            for dep in deps:
                self.db.execute("INSERT INTO dependencies(task_id,depends_on) VALUES(?,?)", (task_id, dep))
            self._event(task_id, "SUBMITTED", {"provider": provider, "dependencies": deps})
            self._checkpoint(task_id, "SUBMITTED", "PARTIAL", "DISPATCH", {"dependencies": deps})
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return self._view(row)

    def get(self, task_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise FabricError(f"Задача не найдена: {task_id}")
        item = self._view(row)
        item["dependencies"] = [r[0] for r in self.db.execute(
            "SELECT depends_on FROM dependencies WHERE task_id=? ORDER BY depends_on", (task_id,))]
        item["checkpoint"] = self.latest_checkpoint(task_id)
        return item

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        return [self._view(r) for r in self.db.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC,id DESC LIMIT ?", (limit,))]

    def claim(self, owner: str, *, provider: str | None = None, lease_seconds: int = 120,
              task_id: str | None = None) -> dict[str, Any] | None:
        if not owner or len(owner) > 120 or lease_seconds < 5 or lease_seconds > 3600:
            raise FabricError("Некорректный исполнитель или срок аренды (от 5 до 3600 секунд)")
        if provider and provider not in PROVIDERS:
            raise FabricError("Неизвестный исполнитель")
        with self.atomic():
            now = time.time()
            row = self.db.execute("""
                SELECT * FROM tasks t WHERE t.status='QUEUED'
                AND (? IS NULL OR t.provider=?)
                AND (? IS NULL OR t.id=?)
                AND NOT EXISTS (
                    SELECT 1 FROM dependencies d
                    JOIN tasks parent ON parent.id=d.depends_on
                    WHERE d.task_id=t.id AND parent.status!='COMPLETE')
                ORDER BY t.created_at,t.id LIMIT 1
            """, (provider, provider, task_id, task_id)).fetchone()
            if row is None:
                return None
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            epoch = row["lease_epoch"] + 1
            deadline = now + lease_seconds
            self.db.execute("""
                UPDATE tasks SET status='RUNNING', lease_owner=?,lease_hash=?,lease_epoch=?,
                    lease_deadline=?,attempt=attempt+1,updated_at=? WHERE id=?
            """, (owner, digest, epoch, deadline, now, row["id"]))
            self._event(row["id"], "CLAIMED", {"owner": owner, "epoch": epoch})
            self._checkpoint(row["id"], "DISPATCHED", "PARTIAL", "EXECUTE",
                             {"owner": owner, "epoch": epoch})
            return {"task_id": row["id"], "lease_token": token, "lease_epoch": epoch,
                    "lease_deadline": deadline, "provider": row["provider"],
                    "objective": row["objective"], "workspace": row["workspace"]}

    def _assert_lease(self, row: sqlite3.Row | None, owner: str, token: str, now: float) -> None:
        if not row or row["status"] != "RUNNING" or row["lease_owner"] != owner:
            raise FabricError("Текущий исполнитель не владеет арендой задачи")
        digest = hashlib.sha256(token.encode()).hexdigest()
        if not row["lease_hash"] or not hmac.compare_digest(row["lease_hash"], digest):
            raise FabricError("Токен аренды не совпадает")
        if row["lease_deadline"] is None or row["lease_deadline"] <= now:
            raise FabricError("Срок аренды истёк; требуется сверка внешних действий")
        if row["cancel_requested"]:
            raise FabricError("Запрошена отмена задачи")

    def heartbeat(self, task_id: str, owner: str, token: str, *, lease_seconds: int = 120) -> dict[str, Any]:
        if lease_seconds < 5 or lease_seconds > 3600:
            raise FabricError("Недопустимый срок аренды")
        with self.atomic():
            now = time.time()
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            self._assert_lease(row, owner, token, now)
            until = now + lease_seconds
            self.db.execute("UPDATE tasks SET lease_deadline=?,updated_at=? WHERE id=?", (until, now, task_id))
            self._event(task_id, "HEARTBEAT", {"epoch": row["lease_epoch"]})
            return {"task_id": task_id, "lease_deadline": until, "lease_epoch": row["lease_epoch"]}

    def checkpoint(self, task_id: str, owner: str, token: str,
                   stage: str, cursor: str, evidence: dict[str, Any],
                   verdict: str = "PARTIAL") -> dict[str, Any]:
        if not isinstance(evidence, dict):
            raise FabricError("Доказательства должны быть объектом JSON")
        with self.atomic():
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            self._assert_lease(row, owner, token, time.time())
            return self._checkpoint(task_id, stage, verdict, cursor, evidence)

    def finish(self, task_id: str, owner: str, token: str, *, verdict: str,
               response: str, evidence: dict[str, Any], cursor: str = "REVIEW",
               external_run_id: str | None = None) -> dict[str, Any]:
        target = {"PASS": "COMPLETE", "PARTIAL": "FAILED", "BLOCKED": "BLOCKED"}.get(verdict)
        if target is None:
            raise FabricError("Недопустимый статус проверки")
        if not isinstance(evidence, dict) or len(response) > 100000:
            raise FabricError("Некорректные доказательства либо слишком длинный ответ")
        with self.atomic():
            now = time.time()
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            self._assert_lease(row, owner, token, now)
            if verdict == "PASS" and self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='effect_operations'"
            ).fetchone():
                unverified = self.db.execute(
                    "SELECT 1 FROM effect_operations WHERE task_id=? "
                    "AND phase!='APPLIED_VERIFIED' LIMIT 1", (task_id,)
                ).fetchone()
                if unverified:
                    raise FabricError("W2: неподтверждённый внешний эффект блокирует PASS")
            self._checkpoint(task_id, "WORKER_RESULT", verdict, cursor,
                             {**evidence, "response_sha256": hashlib.sha256(response.encode()).hexdigest()})
            self.db.execute("""
              UPDATE tasks SET status=?,result_json=?,external_run_id=?,error=?,updated_at=?,
                               lease_owner=NULL,lease_hash=NULL,lease_deadline=NULL WHERE id=?
            """, (target, canonical({"response": response}), external_run_id,
                  (response[:1024] if verdict != "PASS" else None), now, task_id))
            self._event(task_id, "FINISHED", {"verdict": verdict, "status": target})
            return self.get(task_id)

    def latest_checkpoint(self, task_id: str) -> dict[str, Any] | None:
        row = self.db.execute("""
           SELECT * FROM checkpoints WHERE task_id=? ORDER BY seq DESC LIMIT 1
        """, (task_id,)).fetchone()
        if not row:
            return None
        item = {"task_id": row["task_id"], "timestamp": row["timestamp"],
                "stage": row["stage"], "verdict": row["verdict"],
                "cursor": row["cursor"], "evidence": json.loads(row["evidence"])}
        if not hmac.compare_digest(checksum(item), row["content_sha256"]):
            raise FabricError("Нарушена целостность чекпойнта")
        return {**item, "sha256": row["content_sha256"], "sequence": row["seq"]}

    def result(self, task_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT result_json FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise FabricError("Задача не найдена")
        return json.loads(row[0]) if row[0] else None

    def recover(self) -> list[str]:
        # Безопасность: не запускаем просроченного внешнего исполнителя автоматически.
        with self.atomic():
            now = time.time()
            expired = [r[0] for r in self.db.execute(
                "SELECT id FROM tasks WHERE status='RUNNING' AND lease_deadline<=?", (now,))]
            ledger_active = bool(self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='effect_operations'"
            ).fetchone())
            for task_id in expired:
                if ledger_active:
                    # MAY_HAVE_RUN persisted before dispatch; missing ACK is
                    # UNKNOWN_OUTCOME, never automatic retry or PASS.
                    ops = self.db.execute(
                        "SELECT target_id,operation_id FROM effect_operations "
                        "WHERE task_id=? AND phase='MAY_HAVE_RUN'", (task_id,)
                    ).fetchall()
                    for op in ops:
                        self.db.execute(
                            "UPDATE effect_operations SET phase='UNKNOWN_OUTCOME',updated_at=? "
                            "WHERE target_id=? AND operation_id=?",
                            (now, op["target_id"], op["operation_id"]),
                        )
                        self._event(task_id, "EFFECT_ACK_UNKNOWN",
                                    {"target_id": op["target_id"],
                                     "operation_id": op["operation_id"]})
                self.db.execute("""
                  UPDATE tasks SET status='BLOCKED',lease_owner=NULL,lease_hash=NULL,
                        lease_deadline=NULL,updated_at=? WHERE id=?
                """, (now, task_id))
                self._event(task_id, "LEASE_EXPIRED", {"reason": "требуется ручная сверка"})
                self._checkpoint(task_id, "RECOVERY", "BLOCKED", "VERIFY_EXTERNAL_SIDE_EFFECTS",
                                 {"reason": "аренда истекла; запрещено дублировать непроверенный внешний запуск"})
            return expired

    def requeue(self, task_id: str, *, acknowledgement: str) -> dict[str, Any]:
        if len(acknowledgement.strip()) < 12:
            raise FabricError("Для повторной постановки требуется явное подтверждение сверки")
        with self.atomic():
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row or row["status"] not in {"BLOCKED", "FAILED"}:
                raise FabricError("Вернуть в очередь можно только задачи BLOCKED или FAILED")
            if self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='effect_operations'"
            ).fetchone():
                prior_effect = self.db.execute(
                    "SELECT 1 FROM effect_operations WHERE task_id=? LIMIT 1", (task_id,)
                ).fetchone()
                if prior_effect:
                    raise FabricError(
                        "W2: даже сверенный внешний эффект нельзя повторять через requeue; "
                        "требуется отдельная задача и новый operation_id"
                    )
            self.db.execute("UPDATE tasks SET status='QUEUED',cancel_requested=0,updated_at=? WHERE id=?",
                            (time.time(), task_id))
            self._event(task_id, "REQUEUED", {"acknowledgement": acknowledgement[:1024]})
            self._checkpoint(task_id, "REQUEUED", "PARTIAL", "DISPATCH",
                             {"reconciled": True, "note": acknowledgement[:1024]})
            return self.get(task_id)

    def request_cancel(self, task_id: str) -> dict[str, Any]:
        with self.atomic():
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise FabricError("Задача не найдена")
            if row["status"] in TERMINAL:
                return self.get(task_id)
            if row["status"] == "RUNNING":
                # Здесь только запрос: завершить процесс должен отдельный супервизор.
                self.db.execute("UPDATE tasks SET cancel_requested=1,updated_at=? WHERE id=?",
                                (time.time(), task_id))
                self._event(task_id, "CANCELLATION_REQUESTED", {})
            else:
                self.db.execute("UPDATE tasks SET status='CANCELLED',updated_at=? WHERE id=?",
                                (time.time(), task_id))
                self._event(task_id, "CANCELLED", {})
                self._checkpoint(task_id, "CANCELLED", "BLOCKED", "STOP", {"reason": "отмена по запросу оператора"})
            return self.get(task_id)

    def confirm_cancel(self, task_id: str, owner: str, token: str) -> dict[str, Any]:
        with self.atomic():
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row or not row["cancel_requested"] or row["status"] != "RUNNING":
                raise FabricError("Активный запрос отмены отсутствует")
            # Отмену подтверждает только владелец текущей аренды.
            digest = hashlib.sha256(token.encode()).hexdigest()
            if row["lease_owner"] != owner or not hmac.compare_digest(row["lease_hash"], digest):
                raise FabricError("Подтвердить отмену может только действующий владелец аренды")
            self.db.execute("""UPDATE tasks SET status='CANCELLED',lease_owner=NULL,lease_hash=NULL,
                 lease_deadline=NULL,updated_at=? WHERE id=?""", (time.time(), task_id))
            self._event(task_id, "CANCELLED", {"worker_acknowledged": True})
            self._checkpoint(task_id, "CANCELLED", "BLOCKED", "STOP", {"worker_acknowledged": True})
            return self.get(task_id)

    def events(self, task_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return [{"sequence": r[0], "type": r[1], "payload": json.loads(r[2])}
                for r in self.db.execute("""SELECT seq,type,payload FROM events
                   WHERE task_id=? ORDER BY seq DESC LIMIT ?""", (task_id, max(1,min(limit,200))))]
