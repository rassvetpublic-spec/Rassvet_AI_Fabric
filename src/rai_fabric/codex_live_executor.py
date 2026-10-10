"""Один разрешённый Codex App Server turn -> один файл -> локальный unittest.

Никакой API-key, универсальный прокси, автоматическое подтверждение или повтор
модельного turn не предусмотрены. Авторизация выполняется штатным CLI вне модуля.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .codex_real_transport import SafeProtocolError, _owns_binary, _parse_response, _cleanup
from .store import FabricError, FabricStore

_MAX_FRAME = 262144
_MAX_FRAMES = 400
_MAX_REPLY = 8000
_EOF = object()

# Один маленький кодовый результат. Инструменты Codex не используются.
_PROMPT = (
    "Ты выполняешь одну минимальную задачу разработки для Rassvet AI Fabric. "
    "НЕ используй инструменты, shell, поиск, файловые операции или дополнительных агентов. "
    "Верни СТРОГО один JSON-объект без markdown и пояснений: "
    '{"source":"def add(a, b):\\n    return a + b\\n"}. '
    "Это исходник модуля arithmetic.py для сложения чисел. "
    "Без импортов, аннотаций, вызовов других функций и лишнего текста."
)


def _safe_env(home: Path) -> dict[str, str]:
    # Ничего не наследовать из облачной авторизации и платных API переменных.
    allow = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA",
             "APPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMDATA", "COMSPEC",
             "HOMEDRIVE", "HOMEPATH", "NUMBER_OF_PROCESSORS"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allow and v}
    env.update(CODEX_HOME=str(home), NO_COLOR="1", RUST_LOG="error")
    return env


def _safe_json_text(value: str) -> str:
    if not isinstance(value, str) or len(value) > _MAX_REPLY:
        raise SafeProtocolError("MODEL_REPLY_TOO_LONG")
    stripped = value.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        stripped = stripped[7:-3].strip()
    elif stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped[3:-3].strip()
    return stripped


def _no_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for k, v in pairs:
        if k in seen:
            raise SafeProtocolError("MODEL_DUPLICATE_FIELD")
        seen[k] = v
    return seen


def _parse_generated_code(reply: str) -> str:
    try:
        parsed = json.loads(_safe_json_text(reply), object_pairs_hook=_no_duplicate_fields)
    except (ValueError, TypeError) as exc:
        raise SafeProtocolError("MODEL_INVALID_JSON") from exc
    if not isinstance(parsed, dict) or set(parsed) != {"source"}:
        raise SafeProtocolError("MODEL_INVALID_SCHEMA")
    source = parsed["source"]
    if not isinstance(source, str) or len(source) > 1000 or "\r" in source or "\x00" in source:
        raise SafeProtocolError("MODEL_INVALID_SOURCE")
    try:
        module = ast.parse(source)
    except SyntaxError as exc:
        raise SafeProtocolError("MODEL_SOURCE_SYNTAX") from exc
    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        raise SafeProtocolError("MODEL_SOURCE_NOT_ALLOWED")
    func = module.body[0]
    args = func.args
    if (func.name != "add" or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or
            args.defaults or args.kw_defaults or args.args is None or
            [a.arg for a in args.args] != ["a", "b"] or any(a.annotation is not None for a in args.args)
            or func.decorator_list or func.returns is not None or func.type_comment):
        raise SafeProtocolError("MODEL_FUNCTION_NOT_ALLOWED")
    if len(func.body) != 1 or not isinstance(func.body[0], ast.Return):
        raise SafeProtocolError("MODEL_BODY_NOT_ALLOWED")
    expr = func.body[0].value
    if not (isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add)
            and isinstance(expr.left, ast.Name) and expr.left.id == "a"
            and isinstance(expr.right, ast.Name) and expr.right.id == "b"):
        raise SafeProtocolError("MODEL_BODY_NOT_ALLOWED")
    return source.rstrip("\n") + "\n"


def _validate_workspace(path: str | Path) -> Path:
    raw = Path(path)
    if raw.is_symlink():
        raise SafeProtocolError("WORKSPACE_LINK_BLOCKED")
    try:
        work = raw.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise SafeProtocolError("WORKSPACE_MISSING") from exc
    if not work.is_dir() or work.name.casefold() != "workspace":
        raise SafeProtocolError("WORKSPACE_NOT_ISOLATED")
    if os.name == "nt" and "_raif_runtime" not in [p.casefold() for p in work.parts]:
        raise SafeProtocolError("WORKSPACE_NOT_ISOLATED")
    if any(work.iterdir()):
        raise SafeProtocolError("WORKSPACE_NOT_EMPTY")
    return work


def _validate_home(path: str | Path, workspace: Path) -> Path:
    raw = Path(path)
    if raw.is_symlink():
        raise SafeProtocolError("CODEX_HOME_LINK_BLOCKED")
    try:
        home = raw.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise SafeProtocolError("CODEX_HOME_MISSING") from exc
    if not home.is_dir() or home == workspace or home in workspace.parents:
        raise SafeProtocolError("CODEX_HOME_INVALID")
    if os.name == "nt" and "rassvet_ai_fabric" not in [p.casefold() for p in home.parts]:
        raise SafeProtocolError("CODEX_HOME_INVALID")
    return home


def _drive_single_turn(command: list[str], cwd: Path, env: dict[str, str],
                       *, timeout_seconds: float, monitor: Callable[[], bool] | None = None
                       ) -> dict[str, Any]:
    """Только один turn/start, запрет запросов разрешения и командных инструментов."""
    if not (20 <= timeout_seconds <= 300):
        raise SafeProtocolError("BAD_TIMEOUT")
    result: dict[str, Any] = {
        "status": "BLOCKED", "code": "NOT_STARTED", "methods_sent": [],
        "thread_created": False, "turn_started": False, "turn_completed": False,
        "no_auto_approval": True, "single_turn_start": True, "tool_actions_seen": False,
        "reply_sha256": None, "reply_chars": 0, "cleanup": "NOT_STARTED",
        "frames_received": 0, "usage_reported": False,
    }
    pending: queue.Queue[bytes | object] = queue.Queue(maxsize=_MAX_FRAMES + 4)
    child: subprocess.Popen[bytes] | None = None
    reader: threading.Thread | None = None
    deadline = time.monotonic() + timeout_seconds
    thread_id: str | None = None
    turn_id: str | None = None
    deltas: list[str] = []
    completed_item_text = ""
    completed_status: str | None = None
    completed_turn_id: str | None = None

    def send(msg: dict[str, Any]) -> None:
        assert child is not None and child.stdin is not None
        payload = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(payload) > _MAX_FRAME:
            raise SafeProtocolError("OUTBOUND_TOO_LARGE")
        child.stdin.write(payload)
        child.stdin.flush()
        result["methods_sent"].append(msg["method"])

    def process_note(msg: dict[str, Any]) -> None:
        nonlocal completed_status, completed_item_text, completed_turn_id
        method = msg.get("method")
        if not isinstance(method, str):
            raise SafeProtocolError("UNEXPECTED_NOTIFICATION")
        if "id" in msg:
            raise SafeProtocolError("SERVER_APPROVAL_REQUIRED")
        params = msg.get("params")
        if not isinstance(params, dict):
            params = {}
        if thread_id is not None and isinstance(params.get("threadId"), str) and params["threadId"] != thread_id:
            raise SafeProtocolError("WRONG_THREAD_ID")
        if turn_id is not None and isinstance(params.get("turnId"), str) and params["turnId"] != turn_id:
            raise SafeProtocolError("WRONG_TURN_ID")
        if method in ("item/started", "item/completed"):
            item = params.get("item")
            typ = item.get("type") if isinstance(item, dict) else None
            if typ in {"commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "webSearch"}:
                result["tool_actions_seen"] = True
                raise SafeProtocolError("TOOL_EXECUTION_BLOCKED")
            if method == "item/completed" and typ == "agentMessage" and isinstance(item, dict):
                content = item.get("content", [])
                if isinstance(content, list):
                    fragments = [i.get("text", "") for i in content if isinstance(i, dict) and
                                 i.get("type") == "text" and isinstance(i.get("text"), str)]
                    if sum(map(len, fragments)) <= _MAX_REPLY:
                        completed_item_text = "".join(fragments)
        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            if not isinstance(delta, str):
                raise SafeProtocolError("DELTA_NOT_TEXT")
            if sum(map(len, deltas)) + len(delta) > _MAX_REPLY:
                raise SafeProtocolError("REPLY_TOO_LARGE")
            deltas.append(delta)
        if method == "thread/tokenUsage/updated":
            result["usage_reported"] = True
        if method == "turn/completed":
            turn = params.get("turn")
            completed_status = turn.get("status") if isinstance(turn, dict) else None
            completed_turn_id = turn.get("id") if isinstance(turn, dict) else None
            if turn_id is not None and completed_turn_id != turn_id:
                raise SafeProtocolError("WRONG_TURN_ID")

    def take() -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SafeProtocolError("TURN_TIMEOUT")
        if monitor is not None and not monitor():
            raise SafeProtocolError("CANCELLED_OR_LEASE_LOST")
        try:
            item = pending.get(timeout=min(2, remaining))
        except queue.Empty:
            return {}
        if item is _EOF:
            raise SafeProtocolError("SERVER_EOF")
        if not isinstance(item, bytes):
            raise SafeProtocolError("SERVER_READ_FAILED")
        result["frames_received"] += 1
        if result["frames_received"] > _MAX_FRAMES:
            raise SafeProtocolError("TOO_MANY_FRAMES")
        return _parse_response(item)

    def expect(rpc_id: int) -> dict[str, Any]:
        while True:
            msg = take()
            if not msg:
                continue
            if "method" in msg:
                process_note(msg)
                continue
            if type(msg.get("id")) is not int or msg["id"] != rpc_id:
                raise SafeProtocolError("UNEXPECTED_RPC_ID")
            if "error" in msg:
                err = msg["error"]
                # Только числовой error code, никогда сообщение, адрес, token или data.
                val = err.get("code") if isinstance(err, dict) else None
                result["rpc_error_code"] = val if type(val) is int else None
                raise SafeProtocolError("RPC_SERVER_ERROR")
            val = msg.get("result")
            if not isinstance(val, dict):
                raise SafeProtocolError("INVALID_RPC_RESULT")
            return val

    try:
        child = subprocess.Popen(command, cwd=str(cwd), env=env,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, shell=False,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        assert child.stdout is not None

        def read_frames() -> None:
            try:
                while True:
                    frame = child.stdout.readline(_MAX_FRAME + 1)
                    if not frame:
                        break
                    if len(frame) > _MAX_FRAME:
                        try: pending.put(b"{" + b"x" * (_MAX_FRAME + 1), timeout=0.2)
                        except queue.Full: pass
                        break
                    try: pending.put(frame, timeout=0.2)
                    except queue.Full: break
            except Exception:
                pass
            finally:
                try: pending.put(_EOF, timeout=0.2)
                except queue.Full: pass

        reader = threading.Thread(target=read_frames, daemon=True, name="raif-one-live-turn")
        reader.start()
        send({"method":"initialize", "id":1,"params":{
            "clientInfo":{"name":"rassvet_ai_fabric", "title":"Rassvet AI Fabric", "version":"0.1.0"},
            "capabilities":{"experimentalApi":False}}})
        expect(1)
        send({"method":"initialized"})
        send({"method":"thread/start","id":2,"params":{
            "model":None,"cwd":str(cwd),"sandbox":"read-only", "approvalPolicy":"on-request",
            "ephemeral":True,"serviceName":"rassvet_ai_fabric"}})
        thread_reply = expect(2)
        thread = thread_reply.get("thread")
        thread_id = thread.get("id") if isinstance(thread, dict) else None
        if not isinstance(thread_id, str) or not thread_id or len(thread_id) > 256:
            raise SafeProtocolError("THREAD_ID_INVALID")
        result["thread_created"] = True
        send({"method":"turn/start","id":3,"params":{
            "threadId":thread_id, "input":[{"type":"text","text":_PROMPT}]}})
        reply = expect(3)
        turn = reply.get("turn")
        turn_id = turn.get("id") if isinstance(turn, dict) else None
        if not isinstance(turn_id, str) or not turn_id or len(turn_id) > 256:
            raise SafeProtocolError("TURN_ID_INVALID")
        result["turn_started"] = True
        while completed_status is None:
            msg = take()
            if not msg:
                continue
            if "method" in msg:
                process_note(msg)
                continue
            raise SafeProtocolError("UNEXPECTED_RESPONSE")
        if completed_turn_id != turn_id:
            raise SafeProtocolError("WRONG_TURN_ID")
        if completed_status != "completed":
            raise SafeProtocolError("TURN_NOT_COMPLETED")
        result["turn_completed"] = True
        reply_text = "".join(deltas) or completed_item_text
        if len(reply_text) > _MAX_REPLY:
            raise SafeProtocolError("REPLY_TOO_LARGE")
        result["reply_sha256"] = hashlib.sha256(reply_text.encode("utf-8")).hexdigest()
        result["reply_chars"] = len(reply_text)
        # Только в памяти; в сериализованный отчёт или события не попадает.
        result["_private_reply"] = reply_text
        result["status"] = "PASS_WITH_SCOPE"
        result["code"] = "ONE_TURN_COMPLETED"
    except SafeProtocolError as exc:
        result["code"] = exc.code
    except (OSError, BrokenPipeError, ValueError, subprocess.SubprocessError):
        result["code"] = "PROCESS_OR_IO_ERROR"
    finally:
        result["cleanup"] = _cleanup(child)
        if reader is not None:
            reader.join(timeout=1)
        if result["cleanup"] == "CLEANUP_NOT_VERIFIED":
            result["status"] = "BLOCKED"
            result["code"] = "CLEANUP_UNVERIFIED"
            result.pop("_private_reply", None)
    return result


def _test_generated(workspace: Path, source: str, *, python: str = sys.executable) -> dict[str, Any]:
    code = workspace / "arithmetic.py"
    test = workspace / "test_arithmetic.py"
    if code.exists() or test.exists():
        raise SafeProtocolError("OUTPUT_EXISTS")
    code.write_text(source, encoding="utf-8", newline="\n")
    test.write_text(
        "import unittest\nfrom arithmetic import add\n\n"
        "class ArithmeticTests(unittest.TestCase):\n"
        "    def test_positive(self): self.assertEqual(add(2, 3), 5)\n"
        "    def test_zero(self): self.assertEqual(add(0, 7), 7)\n"
        "    def test_negative(self): self.assertEqual(add(-2, -4), -6)\n",
        encoding="utf-8", newline="\n")
    completed = subprocess.run([python, "-I", "-B", "-m", "unittest", "discover", "-s",
                                str(workspace), "-p", "test_arithmetic.py", "-q"],
                               cwd=str(workspace), timeout=15,
                               capture_output=True, text=True, env=_safe_env(workspace))
    return {"passed": completed.returncode == 0,
            "local_test_count": 3 if completed.returncode == 0 else 0,
            "source_sha256": hashlib.sha256(code.read_bytes()).hexdigest(),
            "test_sha256": hashlib.sha256(test.read_bytes()).hexdigest()}


def run_live_task(store: FabricStore, *, task_id: str, binary: str | Path, codex_home: str | Path,
                  workspace: str | Path, expected_binary_sha256: str, one_turn_consent: bool,
                  timeout_seconds: int = 120,
                  driver: Callable[..., dict[str, Any]] = _drive_single_turn) -> dict[str, Any]:
    """Захват точно указанной задачи; блокировка повторного модельного обращения."""
    if not one_turn_consent:
        raise FabricError("Нужен явный флаг разрешения на один модельный turn")
    if not (30 <= timeout_seconds <= 300):
        raise FabricError("Недопустимый тайм-аут")
    folder = _validate_workspace(workspace)
    home = _validate_home(codex_home, folder)
    exe = _owns_binary(binary)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_binary_sha256):
        raise SafeProtocolError("BINARY_PIN_INVALID")
    sha = hashlib.sha256(exe.read_bytes()).hexdigest()
    if sha.casefold() != expected_binary_sha256.casefold():
        raise SafeProtocolError("CODEX_BINARY_CHANGED")
    task = store.get(task_id)
    if task["provider"] != "codex-app" or Path(task["workspace"]) != folder or task["status"] != "QUEUED":
        raise FabricError("Задача не является ожидаемой новой codex-app задачей")
    owner = "raif-live-once"
    lease = store.claim(owner, provider="codex-app", task_id=task_id,
                        lease_seconds=min(3600, timeout_seconds + 60))
    if lease is None:
        raise FabricError("Аренда задачи не получена; модель не запускалась")
    token = lease["lease_token"]
    due = time.monotonic()

    def monitor() -> bool:
        nonlocal due
        if store.get(task_id)["cancel_requested"]:
            return False
        if time.monotonic() >= due:
            try:
                store.heartbeat(task_id, owner, token, lease_seconds=min(3600, timeout_seconds + 60))
            except FabricError:
                return False
            due = time.monotonic() + 15
        return True

    outcome: dict[str, Any] = {"status":"BLOCKED","code":"NO_RESULT","cleanup":"NOT_STARTED"}
    evidence: dict[str, Any] = {"provider":"codex-app","simulation":False,
                                "consent_one_turn":True,"api_key_fallback":False}
    code = "UNKNOWN"
    try:
        outcome = driver([str(exe),"app-server","--listen","stdio://"], folder,
                         _safe_env(home), timeout_seconds=timeout_seconds, monitor=monitor)
        code = str(outcome.get("code", "UNKNOWN"))[:64]
        evidence.update({"driver_code":code,"method_names":outcome.get("methods_sent",[]),
                         "model_turn_sent":"turn/start" in outcome.get("methods_sent", []),
                         "model_turn_sent":"turn/start" in outcome.get("methods_sent", []),
            "model_turn_started":bool(outcome.get("turn_started")),
                         "model_turn_completed":bool(outcome.get("turn_completed")),
                         "tool_actions_seen":bool(outcome.get("tool_actions_seen")),
                         "child_cleanup":outcome.get("cleanup", "UNKNOWN"),
                         "usage_reported":bool(outcome.get("usage_reported"))})
        if outcome.get("status") != "PASS_WITH_SCOPE":
            raise SafeProtocolError(code)
        source = _parse_generated_code(outcome.pop("_private_reply", ""))
        tested = _test_generated(folder, source)
        evidence.update(tested)
        if not tested["passed"]:
            raise SafeProtocolError("LOCAL_TESTS_FAILED")
        code = "MODEL_CODE_GENERATED_AND_TESTED"
        result_status = "PASS"
    except (SafeProtocolError, OSError, ValueError, subprocess.SubprocessError) as exc:
        code = exc.code if isinstance(exc, SafeProtocolError) else "LOCAL_PROCESS_FAILED"
        result_status = "BLOCKED"
        evidence["local_blocker"] = code
    # Fail closed, no requeue or retry, no raw model output in SQLite.
    try:
        if store.get(task_id)["cancel_requested"]:
            final = store.confirm_cancel(task_id, owner, token)
        else:
            final = store.finish(task_id, owner, token, verdict=result_status,
                                 response=code, evidence=evidence,
                                 cursor="REVIEW_GENERATED_CODE" if result_status=="PASS"
                                 else "VERIFY_EXTERNAL_SIDE_EFFECTS")
    except FabricError:
        return {"status":"BLOCKED","code":"LEASE_STATE_UNKNOWN",
                "task_id":task_id,"requires_manual_reconciliation":True}
    return {"status":final["status"], "code":code,
            "task_id":task_id,"checkpoint":final.get("checkpoint"),
            "source_created":(folder / "arithmetic.py").is_file(),
            "model_turn_sent":"turn/start" in outcome.get("methods_sent", []),
            "model_turn_started":bool(outcome.get("turn_started")),
            "model_turn_completed":bool(outcome.get("turn_completed"))}


def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser(description="Одно разрешённое задание Codex через очередь Fabric")
    p.add_argument("--db",required=True);p.add_argument("--task-id",required=True)
    p.add_argument("--binary",required=True);p.add_argument("--codex-home",required=True)
    p.add_argument("--workspace",required=True);p.add_argument("--expected-sha256",required=True)
    p.add_argument("--timeout",type=int,default=120)
    p.add_argument("--consent-one-turn",action="store_true")
    a=p.parse_args(argv)
    try:
        with FabricStore(a.db) as store:
            result=run_live_task(store,task_id=a.task_id,binary=a.binary,
                codex_home=a.codex_home,workspace=a.workspace,
                expected_binary_sha256=a.expected_sha256,
                one_turn_consent=a.consent_one_turn,timeout_seconds=a.timeout)
    except (FabricError, SafeProtocolError, OSError, ValueError) as exc:
        result={"status":"BLOCKED", "code":exc.code if isinstance(exc,SafeProtocolError)
                else "PRECONDITION_FAILED", "model_turn_started":False}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["status"]=="COMPLETE" else 3


if __name__=="__main__":
    raise SystemExit(main())
