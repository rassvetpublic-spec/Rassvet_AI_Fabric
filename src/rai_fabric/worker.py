"""Явно включаемые исполнители, без веб-скрейпинга и платного API fallback."""
from __future__ import annotations

__version__ = "1.0.0"

import json
import os
import shutil
import subprocess
import time
import uuid
from typing import Any

from .store import FabricError, FabricStore


def run_one(store: FabricStore, provider: str, *, allow_external: bool = False,
            timeout_seconds: int = 300, owner: str | None = None) -> dict[str, Any]:
    # W2 is explicitly opt-in for a fresh DB. External providers have no
    # verified target receipt adapter yet: refuse BEFORE claiming or spawning.
    version = store.db.execute(
        "SELECT value FROM meta WHERE key='schema_version'"
    ).fetchone()
    if version and version[0] == "2" and provider not in {"mock", "codex-mock"}:
        raise FabricError("W2: внешний worker заблокирован до verified effect adapter")
    if provider == "codex-app":
        raise FabricError("Драйвер Codex App Server не реализован в 0.1.0; задача не захвачена")
    if provider not in {"mock", "codex-mock", "antigravity"}:
        raise FabricError("Исполнение через этого провайдера не поддерживается")
    if provider == "antigravity" and not allow_external:
        raise FabricError("Для внешнего исполнителя требуется --allow-external; задача не захвачена")
    if provider == "antigravity" and not shutil.which("agy"):
        raise FabricError("Antigravity CLI (agy) недоступен; задача не захвачена")
    if provider == "antigravity" and str(shutil.which("agy")).lower().endswith((".cmd", ".bat")):
        raise FabricError("Запуск .cmd/.bat в Windows требует проверенной безопасной передачи аргументов; задача не захвачена")
    if timeout_seconds < 5 or timeout_seconds > 3600:
        raise FabricError("Тайм-аут должен составлять от 5 до 3600 секунд")
    owner = owner or f"rai-local-{uuid.uuid4().hex[:8]}"
    claim = store.claim(owner, provider=provider, lease_seconds=min(3600, max(120, timeout_seconds + 30)))
    if claim is None:
        return {"status": "NO_READY_TASK", "provider": provider}
    task_id, token = claim["task_id"], claim["lease_token"]
    try:
        if provider == "mock":
            response = f"Имитатор принял задачу {task_id}: {claim['objective'][:160]}"
            evidence = {"provider": "mock", "simulation": True, "external_cost": 0}
            # Имитатор проверяет обмен, а не выполнение самой задачи.
            # PASS означает успех тестового транспорта; в доказательствах указана имитация.
            verdict = "PASS"
            external_id = None
        elif provider == "codex-mock":
            # Имитатор является отдельным провайдером; никогда не выдаём его за codex-app.
            from .codex_mock_transport import run_codex_mock
            outcome = run_codex_mock(timeout_seconds=min(30, timeout_seconds))
            verdict = outcome["verdict"] or "BLOCKED"
            response = outcome["response"] or "Подставной процесс завершился без ответа"
            evidence = {
                "provider": "codex-mock", "simulation": True, "real_codex": False,
                "external_model_calls": 0, "billing": "NONE",
                "protocol_state": outcome["state"], "protocol_cursor": outcome["cursor"],
                "protocol_error": outcome["error_code"],
            }
            external_id = None
        else:
            response, evidence, verdict, external_id = _run_antigravity(
                store, claim, owner, token, timeout_seconds)
        if store.get(task_id)["cancel_requested"]:
            return store.confirm_cancel(task_id, owner, token)
        if provider == "codex-mock":
            cursor = ("REVIEW_EVIDENCE" if verdict == "PASS" else
                      evidence.get("protocol_cursor", "VERIFY_EXTERNAL_SIDE_EFFECTS"))
        else:
            cursor = "REVIEW" if verdict == "PASS" else "RECONCILE"
        return store.finish(task_id, owner, token, verdict=verdict, response=response,
                            evidence=evidence, cursor=cursor, external_run_id=external_id)
    except Exception as exc:
        # Внешние побочные эффекты могли уже возникнуть: повтор запрещён до сверки.
        if store.get(task_id)["cancel_requested"]:
            return store.confirm_cancel(task_id, owner, token)
        return store.finish(task_id, owner, token, verdict="BLOCKED",
                            response=f"Ошибка исполнения задачи ({type(exc).__name__}): {str(exc)[:600]}",
                            evidence={"provider": provider, "reconcile_before_retry": True},
                            cursor="VERIFY_EXTERNAL_SIDE_EFFECTS")


def _run_antigravity(store: FabricStore, claim: dict[str, Any], owner: str,
                     token: str, timeout_seconds: int) -> tuple[str, dict[str, Any], str, str | None]:
    executable = shutil.which("agy")
    if not executable:
        raise FabricError("Исполняемый файл Antigravity стал недоступен")
    cmd = [executable, "-p", claim["objective"], "--output-format", "json", "--sandbox"]
    # Не передаём флаги обхода разрешений, браузерные команды или API-ключи.
    env = os.environ.copy()
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                 "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY", "GITHUB_TOKEN",
                 "GH_TOKEN", "RAI_LEASE_TOKEN"):
        env.pop(name, None)
    proc = subprocess.Popen(cmd, cwd=claim["workspace"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=min(3, max(0.1, deadline - time.monotonic())))
            break
        except subprocess.TimeoutExpired:
            if store.get(claim["task_id"])["cancel_requested"]:
                proc.terminate()
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                return "Выполнение отменено оператором", {"provider": "antigravity", "cancelled": True}, "BLOCKED", None
            if time.monotonic() >= deadline:
                proc.kill()
                proc.communicate()
                return "Превышено время выполнения Antigravity; проверьте побочные эффекты", {"timeout": timeout_seconds}, "BLOCKED", None
            store.heartbeat(claim["task_id"], owner, token,
                            lease_seconds=min(3600, max(120, timeout_seconds + 30)))
    if len(stdout) > 200000:
        return "Слишком большой ответ исполнителя", {"stdout_bytes": len(stdout)}, "BLOCKED", None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return "Antigravity вернул не-JSON; проверьте локальные журналы", {
            "exit_code": proc.returncode, "stderr_redacted": True}, "BLOCKED", None
    external_id = data.get("conversation_id") if isinstance(data.get("conversation_id"), str) else None
    success = proc.returncode == 0 and data.get("status") == "SUCCESS"
    # Кода завершения CLI недостаточно: возможен отказ или ожидание разрешения.
    evidence = {"provider": "antigravity", "exit_code": proc.returncode,
                "reported_status": str(data.get("status", "UNKNOWN")),
                "usage": data.get("usage", {}), "sandbox": True}
    response = str(data.get("response", ""))[:100000]
    return response, evidence, ("PASS" if success else "BLOCKED"), external_id
