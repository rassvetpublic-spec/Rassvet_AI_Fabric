"""Opt-in provider runner; no browser scraping and no API-billed fallback."""
from __future__ import annotations

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
    if provider == "codex-app":
        raise FabricError("Codex App Server driver is not implemented in v0.1.0; no job was claimed")
    if provider not in {"mock", "antigravity"}:
        raise FabricError("Unsupported executable provider")
    if provider == "antigravity" and not allow_external:
        raise FabricError("An external provider requires --allow-external; no job was claimed")
    if provider == "antigravity" and not shutil.which("agy"):
        raise FabricError("Antigravity CLI (agy) is not available; no job was claimed")
    if provider == "antigravity" and str(shutil.which("agy")).lower().endswith((".cmd", ".bat")):
        raise FabricError("Windows batch shim requires a verified argument-safe launcher; no job was claimed")
    if timeout_seconds < 5 or timeout_seconds > 3600:
        raise FabricError("Timeout must be 5..3600 seconds")
    owner = owner or f"rai-local-{uuid.uuid4().hex[:8]}"
    claim = store.claim(owner, provider=provider, lease_seconds=min(3600, max(120, timeout_seconds + 30)))
    if claim is None:
        return {"status": "NO_READY_TASK", "provider": provider}
    task_id, token = claim["task_id"], claim["lease_token"]
    try:
        if provider == "mock":
            response = f"Mock execution acknowledged task {task_id}: {claim['objective'][:160]}"
            evidence = {"provider": "mock", "simulation": True, "external_cost": 0}
            # Mock proves plumbing, not that the task objective was implemented.
            # PASS means the mock transport worked; evidence explicitly marks simulation.
            verdict = "PASS"
            external_id = None
        else:
            response, evidence, verdict, external_id = _run_antigravity(
                store, claim, owner, token, timeout_seconds)
        if store.get(task_id)["cancel_requested"]:
            return store.confirm_cancel(task_id, owner, token)
        return store.finish(task_id, owner, token, verdict=verdict, response=response,
                            evidence=evidence, cursor=("REVIEW" if verdict == "PASS" else "RECONCILE"),
                            external_run_id=external_id)
    except Exception as exc:
        # External side effects could already exist; do not retry automatically.
        if store.get(task_id)["cancel_requested"]:
            return store.confirm_cancel(task_id, owner, token)
        return store.finish(task_id, owner, token, verdict="BLOCKED",
                            response=f"Worker runtime error ({type(exc).__name__}): {str(exc)[:600]}",
                            evidence={"provider": provider, "reconcile_before_retry": True},
                            cursor="VERIFY_EXTERNAL_SIDE_EFFECTS")


def _run_antigravity(store: FabricStore, claim: dict[str, Any], owner: str,
                     token: str, timeout_seconds: int) -> tuple[str, dict[str, Any], str, str | None]:
    executable = shutil.which("agy")
    if not executable:
        raise FabricError("Antigravity executable disappeared")
    cmd = [executable, "-p", claim["objective"], "--output-format", "json", "--sandbox"]
    # Explicitly omit --dangerously-skip-permissions, browser automation, and API keys.
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
                return "Cancelled by operator", {"provider": "antigravity", "cancelled": True}, "BLOCKED", None
            if time.monotonic() >= deadline:
                proc.kill()
                proc.communicate()
                return "Antigravity timed out; inspect side effects", {"timeout": timeout_seconds}, "BLOCKED", None
            store.heartbeat(claim["task_id"], owner, token,
                            lease_seconds=min(3600, max(120, timeout_seconds + 30)))
    if len(stdout) > 200000:
        return "Oversized provider output", {"stdout_bytes": len(stdout)}, "BLOCKED", None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return "Antigravity returned non-JSON output; inspect local logs", {
            "exit_code": proc.returncode, "stderr_redacted": True}, "BLOCKED", None
    external_id = data.get("conversation_id") if isinstance(data.get("conversation_id"), str) else None
    success = proc.returncode == 0 and data.get("status") == "SUCCESS"
    # The CLI exit code alone is insufficient (e.g. waiting for permissions).
    evidence = {"provider": "antigravity", "exit_code": proc.returncode,
                "reported_status": str(data.get("status", "UNKNOWN")),
                "usage": data.get("usage", {}), "sandbox": True}
    response = str(data.get("response", ""))[:100000]
    return response, evidence, ("PASS" if success else "BLOCKED"), external_id
