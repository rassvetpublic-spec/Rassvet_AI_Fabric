"""W2: SQLite-журнал намерений и fail-closed восстановление внешних эффектов.

Это НЕ runtime-разрешение внешнего провайдера. Единственная реализованная
сверка — синтетический SQLite-приёмник в отдельной тестовой базе.
"""
from __future__ import annotations

__version__ = "0.1.0"

import hashlib
import hmac
import re
import sqlite3
import stat
import time
from pathlib import Path

from .store import FabricError, FabricStore, canonical

_PHASES = frozenset({
    "PREPARED", "MAY_HAVE_RUN", "APPLIED_VERIFIED",
    "NO_EFFECT_VERIFIED", "UNKNOWN_OUTCOME", "BLOCKED_RECONCILE",
})
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_REPARSE = 0x400


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        raise FabricError("Некорректный неприватный идентификатор эффекта")
    return value


def _sha(value: str) -> str:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise FabricError("Требуется SHA-256, а не исходный payload")
    return value


def _safe_parent(path: Path) -> bool:
    """Статический fail-closed preflight для тестового SQLite-приёмника."""
    current = path
    while True:
        try:
            meta = current.lstat()
        except OSError:
            return False
        if stat.S_ISLNK(meta.st_mode) or getattr(meta, "st_file_attributes", 0) & _REPARSE:
            return False
        if current.parent == current:
            return True
        current = current.parent


class SyntheticSQLiteTarget:
    """Только для локального тестирования потери ACK, НЕ внешний target-adapter."""

    def __init__(self, path: str | Path, target_id: str, *, initialize: bool = False):
        self.target_id = _identifier(target_id)
        original = Path(path).expanduser().absolute()
        if not _safe_parent(original.parent) or original.is_symlink():
            raise FabricError("Тестовый SQLite target использует небезопасный путь")
        if initialize and original.exists():
            raise FabricError("Тестовый SQLite target создаётся только новым файлом")
        if not initialize and not original.is_file():
            raise FabricError("Тестовый SQLite target должен быть создан явно")
        if original.exists() and not original.is_file():
            raise FabricError("Путь target не является обычным файлом")
        self.path = original
        self.db = sqlite3.connect(str(original), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA synchronous=FULL")
        if initialize:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS synthetic_effects ("
                "target_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
                "payload_sha256 TEXT NOT NULL, revision INTEGER NOT NULL, "
                "PRIMARY KEY(target_id,operation_id))"
            )
        elif not self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='synthetic_effects'"
        ).fetchone():
            self.close()
            raise FabricError("Отсутствует схема синтетического target")

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "SyntheticSQLiteTarget":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def apply(self, operation_id: str, payload_sha256: str) -> dict:
        """Идемпотентная запись в отдельный локальный sink; без сетевого вызова."""
        op = _identifier(operation_id)
        digest = _sha(payload_sha256)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.db.execute(
                "SELECT * FROM synthetic_effects WHERE target_id=? AND operation_id=?",
                (self.target_id, op),
            ).fetchone()
            if previous and previous["payload_sha256"] != digest:
                raise FabricError("Конфликт повторного применения к target")
            if previous is None:
                self.db.execute(
                    "INSERT INTO synthetic_effects(target_id,operation_id,payload_sha256,revision) "
                    "VALUES(?,?,?,1)", (self.target_id, op, digest),
                )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self.readback(op)

    def readback(self, operation_id: str) -> dict | None:
        op = _identifier(operation_id)
        row = self.db.execute(
            "SELECT payload_sha256,revision FROM synthetic_effects "
            "WHERE target_id=? AND operation_id=?",
            (self.target_id, op),
        ).fetchone()
        if row is None:
            return None
        return {"target_id": self.target_id, "operation_id": op,
                "payload_sha256": row["payload_sha256"], "revision": row["revision"]}


class EffectLedger:
    """Явный W2 opt-in к уже существующей FabricStore; второго TaskGraph нет."""

    def __init__(self, store: FabricStore):
        if not isinstance(store, FabricStore):
            raise FabricError("Требуется существующее FabricStore")
        self.store = store
        version = store.db.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        if not version or version[0] != "2":
            raise FabricError("W2 schema отсутствует; нужен отдельный opt-in")
        for name in ("effect_operations", "effect_receipts"):
            if not store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone():
                raise FabricError("Неполная схема W2 ledger")
        store.db.execute("PRAGMA synchronous=FULL")

    @classmethod
    def install_on_empty_store(cls, store: FabricStore) -> "EffectLedger":
        """Создать W2-таблицы только в пустой явно выбранной Fabric SQLite БД."""
        if not isinstance(store, FabricStore):
            raise FabricError("Неизвестное хранилище")
        with store.atomic():
            version = store.db.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if not version or version[0] != "1":
                raise FabricError("W2 не мигрирует существующую БД автоматически")
            count = store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            if count != 0:
                raise FabricError("W2 schema допускается только в пустой тестовой БД")
            store.db.execute("""
                CREATE TABLE effect_operations (
                  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
                  target_id TEXT NOT NULL,
                  operation_id TEXT NOT NULL,
                  payload_sha256 TEXT NOT NULL,
                  lease_epoch INTEGER NOT NULL CHECK(lease_epoch>0),
                  expected_revision TEXT NOT NULL,
                  phase TEXT NOT NULL CHECK(phase IN
                    ('PREPARED','MAY_HAVE_RUN','APPLIED_VERIFIED',
                     'NO_EFFECT_VERIFIED','UNKNOWN_OUTCOME','BLOCKED_RECONCILE')),
                  created_at REAL NOT NULL, updated_at REAL NOT NULL,
                  PRIMARY KEY(target_id, operation_id)
                )
            """)
            store.db.execute(
                "CREATE INDEX idx_effect_task ON effect_operations(task_id,phase)"
            )
            store.db.execute("""
                CREATE TABLE effect_receipts (
                  receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  target_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                  verdict TEXT NOT NULL CHECK(verdict IN
                    ('APPLIED_VERIFIED','NO_EFFECT_VERIFIED')),
                  target_revision TEXT NOT NULL,
                  applied_sha256 TEXT NOT NULL,
                  evidence_sha256 TEXT NOT NULL,
                  readback_class TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  UNIQUE(target_id,operation_id),
                  FOREIGN KEY(target_id,operation_id)
                    REFERENCES effect_operations(target_id,operation_id)
                )
            """)
            for operation in ("UPDATE", "DELETE"):
                store.db.execute(
                    "CREATE TRIGGER immutable_effect_receipt_" + operation.lower()
                    + " BEFORE " + operation + " ON effect_receipts "
                    + "BEGIN SELECT RAISE(ABORT,'EFFECT_RECEIPT_IMMUTABLE'); END"
                )
            store.db.execute(
                "UPDATE meta SET value='2' WHERE key='schema_version'"
            )
        return cls(store)

    @staticmethod
    def _view(row: sqlite3.Row) -> dict:
        return {k: row[k] for k in (
            "task_id", "target_id", "operation_id", "payload_sha256",
            "lease_epoch", "expected_revision", "phase", "created_at", "updated_at",
        )}

    def _operation(self, target_id: str, operation_id: str) -> sqlite3.Row:
        row = self.store.db.execute(
            "SELECT * FROM effect_operations WHERE target_id=? AND operation_id=?",
            (_identifier(target_id), _identifier(operation_id)),
        ).fetchone()
        if row is None:
            raise FabricError("Эффект не зарегистрирован в ledger")
        return row

    def get(self, target_id: str, operation_id: str) -> dict:
        return self._view(self._operation(target_id, operation_id))

    def list_for_task(self, task_id: str) -> list[dict]:
        return [self._view(row) for row in self.store.db.execute(
            "SELECT * FROM effect_operations WHERE task_id=? ORDER BY target_id,operation_id",
            (task_id,),
        )]

    def prepare_effect(self, task_id: str, owner: str, lease_token: str, *,
                       target_id: str, operation_id: str,
                       payload_sha256: str, expected_revision: str) -> dict:
        """Ledger PREPARED коммитится ДО любой возможной внешней операции."""
        target, op = _identifier(target_id), _identifier(operation_id)
        payload, revision = _sha(payload_sha256), _identifier(expected_revision)
        with self.store.atomic():
            now = time.time()
            row = self.store.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            self.store._assert_lease(row, owner, lease_token, now)
            old = self.store.db.execute(
                "SELECT * FROM effect_operations WHERE target_id=? AND operation_id=?",
                (target, op),
            ).fetchone()
            if old:
                same = (
                    old["task_id"] == task_id and old["payload_sha256"] == payload
                    and old["expected_revision"] == revision
                    and old["lease_epoch"] == row["lease_epoch"]
                )
                if not same:
                    raise FabricError("OPERATION_ID_CONFLICT: эффект нельзя переопределить")
                return self._view(old)
            self.store.db.execute(
                "INSERT INTO effect_operations "
                "(task_id,target_id,operation_id,payload_sha256,lease_epoch,"
                "expected_revision,phase,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,'PREPARED',?,?)",
                (task_id, target, op, payload, row["lease_epoch"], revision, now, now),
            )
            self.store._event(task_id, "EFFECT_PREPARED",
                              {"target_id": target, "operation_id": op, "epoch": row["lease_epoch"]})
            return self._view(self._operation(target, op))

    def mark_possible_dispatch(self, task_id: str, owner: str, lease_token: str, *,
                               target_id: str, operation_id: str) -> dict:
        """Одноразовый fence; MUST commit before invoking any outside target."""
        with self.store.atomic():
            now = time.time()
            row = self.store.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            self.store._assert_lease(row, owner, lease_token, now)
            op = self._operation(target_id, operation_id)
            if (op["task_id"] != task_id or op["lease_epoch"] != row["lease_epoch"]
                    or op["phase"] != "PREPARED"):
                raise FabricError("Внешнее действие уже могло начаться; повтор запрещён")
            self.store.db.execute(
                "UPDATE effect_operations SET phase='MAY_HAVE_RUN',updated_at=? "
                "WHERE target_id=? AND operation_id=? AND phase='PREPARED'",
                (now, op["target_id"], op["operation_id"]),
            )
            self.store._event(task_id, "EFFECT_MAY_HAVE_RUN",
                              {"target_id": op["target_id"], "operation_id": op["operation_id"]})
            return self._view(self._operation(op["target_id"], op["operation_id"]))

    def recover_pending_effects(self) -> list[dict]:
        """После crash/lost ACK пометить просроченные MAY_HAVE_RUN как UNKNOWN."""
        changed = []
        with self.store.atomic():
            now = time.time()
            rows = self.store.db.execute("""
              SELECT e.* FROM effect_operations e JOIN tasks t ON t.id=e.task_id
              WHERE e.phase='MAY_HAVE_RUN'
              AND (t.status IN ('BLOCKED','FAILED','CANCELLED')
                   OR (t.status='RUNNING' AND t.lease_deadline<=?))
              ORDER BY e.target_id,e.operation_id
            """, (now,)).fetchall()
            for row in rows:
                self.store.db.execute(
                    "UPDATE effect_operations SET phase='UNKNOWN_OUTCOME',updated_at=? "
                    "WHERE target_id=? AND operation_id=?",
                    (now, row["target_id"], row["operation_id"]),
                )
                self.store._event(row["task_id"], "EFFECT_ACK_UNKNOWN",
                                  {"target_id": row["target_id"],
                                   "operation_id": row["operation_id"]})
                changed.append(self._view(self._operation(row["target_id"], row["operation_id"])))
        return changed

    def reconcile_synthetic(self, target: SyntheticSQLiteTarget, operation_id: str) -> dict:
        """Сверять эффект ТОЛЬКО с независимой локальной synthetic SQLite БД.

        Отсутствие записи после MAY_HAVE_RUN не доказывает, что эффекта не было
        или что запущенный процесс не внесёт запись позднее.
        """
        if type(target) is not SyntheticSQLiteTarget or target.path == self.store.path:
            raise FabricError("Требуется отдельный проверенный synthetic target")
        op = self._operation(target.target_id, operation_id)
        proof = target.readback(operation_id)
        with self.store.atomic():
            op = self._operation(target.target_id, operation_id)
            if op["phase"] in ("APPLIED_VERIFIED", "NO_EFFECT_VERIFIED"):
                return self._view(op)
            now = time.time()
            if proof is None and op["phase"] == "PREPARED":
                verdict = "NO_EFFECT_VERIFIED"
                revision = "0"
                applied = "0" * 64
                proof_class = "SYNTHETIC_PREPARED_UNDISPATCHED"
            elif (proof is not None and op["phase"] in
                  ("MAY_HAVE_RUN", "UNKNOWN_OUTCOME", "BLOCKED_RECONCILE")
                  and proof["payload_sha256"] == op["payload_sha256"]
                  and op["expected_revision"] == "rev-0"
                  and proof["revision"] == 1):
                verdict = "APPLIED_VERIFIED"
                revision = str(proof["revision"])
                applied = proof["payload_sha256"]
                proof_class = "SYNTHETIC_SQLITE_TARGET_READBACK"
            else:
                # Mismatch, missing ACK, a possible late process, or unexpected
                # out-of-band dispatch: no fabricated success or automatic retry.
                self.store.db.execute(
                    "UPDATE effect_operations SET phase='BLOCKED_RECONCILE',updated_at=? "
                    "WHERE target_id=? AND operation_id=?",
                    (now, op["target_id"], op["operation_id"]),
                )
                self.store._event(op["task_id"], "EFFECT_RECONCILE_BLOCKED",
                                  {"target_id": op["target_id"],
                                   "operation_id": op["operation_id"]})
                return self._view(self._operation(op["target_id"], op["operation_id"]))
            receipt_meta = {
                "target_id": op["target_id"], "operation_id": op["operation_id"],
                "verdict": verdict, "revision": revision, "applied_sha256": applied,
                "readback_class": proof_class,
            }
            evidence_sha256 = hashlib.sha256(canonical(receipt_meta).encode("utf-8")).hexdigest()
            self.store.db.execute(
                "INSERT INTO effect_receipts "
                "(target_id,operation_id,verdict,target_revision,applied_sha256,"
                "evidence_sha256,readback_class,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (op["target_id"], op["operation_id"], verdict, revision, applied,
                 evidence_sha256, proof_class, now),
            )
            self.store.db.execute(
                "UPDATE effect_operations SET phase=?,updated_at=? "
                "WHERE target_id=? AND operation_id=?",
                (verdict, now, op["target_id"], op["operation_id"]),
            )
            self.store._event(op["task_id"], "EFFECT_SYNTHETIC_READBACK",
                              {"target_id": op["target_id"], "operation_id": op["operation_id"],
                               "verdict": verdict, "evidence_sha256": evidence_sha256})
            return self._view(self._operation(op["target_id"], op["operation_id"]))

    def receipts_for_task(self, task_id: str) -> list[dict]:
        rows = self.store.db.execute(
            "SELECT r.target_id,r.operation_id,r.verdict,r.target_revision,"
            "r.applied_sha256,r.evidence_sha256,r.readback_class FROM effect_receipts r "
            "JOIN effect_operations e ON r.target_id=e.target_id AND r.operation_id=e.operation_id "
            "WHERE e.task_id=? ORDER BY r.receipt_id", (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]
