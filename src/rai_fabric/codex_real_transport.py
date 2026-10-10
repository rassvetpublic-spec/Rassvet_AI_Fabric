"""Управляемый App Server: только initialize и необязательный thread/start.

Ни turn/start, ни OAuth, ни платные API не вызываются этим модулем.
Рабочая сессия ограничивается отдельными CODEX_HOME и workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

_MAX_LINE = 262144
_MAX_MESSAGES = 128
_EOF = object()


class SafeProtocolError(Exception):
    """Не содержите в сообщениях исключений значения полученных RPC-полей."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise SafeProtocolError("DUPLICATE_JSON_KEY")
        out[k] = v
    return out


def _bad_json_number(value: str) -> None:
    raise SafeProtocolError("INVALID_JSON_CONSTANT")


def _parse_response(frame: bytes) -> dict[str, Any]:
    if len(frame) > _MAX_LINE or not frame.endswith(b"\n"):
        raise SafeProtocolError("OVERSIZED_OR_PARTIAL_FRAME")
    try:
        value = json.loads(frame.decode("utf-8"), object_pairs_hook=_unique_json,
                           parse_constant=_bad_json_number)
    except (UnicodeDecodeError, ValueError) as exc:
        raise SafeProtocolError("INVALID_JSONL_FRAME") from exc
    if not isinstance(value, dict):
        raise SafeProtocolError("RPC_FRAME_NOT_OBJECT")
    return value


def _environment(private_home: str) -> dict[str, str]:
    allow = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA",
             "APPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMDATA",
             "HOMEDRIVE", "HOMEPATH", "COMSPEC")
    env = {k: v for k, v in os.environ.items() if k.upper() in allow and v}
    env.update(CODEX_HOME=private_home, NO_COLOR="1", CI="true")
    return env


def _owns_binary(path: str | Path) -> Path:
    item = Path(path)
    if item.is_symlink() or item.name.casefold() != "codex.exe" or not item.is_file():
        raise SafeProtocolError("CODEX_EXECUTABLE_NOT_ALLOWLISTED")
    try:
        resolved = item.resolve(strict=True)
    except OSError as exc:
        raise SafeProtocolError("CODEX_EXECUTABLE_MISSING") from exc
    if resolved.name.casefold() != "codex.exe":
        raise SafeProtocolError("CODEX_EXECUTABLE_NOT_ALLOWLISTED")
    return resolved


def _cleanup(proc: subprocess.Popen[bytes] | None) -> str:
    if proc is None:
        return "NOT_STARTED"
    try:
        if proc.poll() is None:
            if proc.stdin:
                proc.stdin.close()
            try:
                proc.wait(timeout=2.5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    # Только созданный нами PID; taskkill /T завершает дочернее дерево.
                    subprocess.run(["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=4, check=False)
                else:
                    proc.kill()
                proc.wait(timeout=2.0)
                return "FORCED_OWN_CHILD_TREE" if os.name == "nt" else "FORCED_OWN_CHILD"
        return "GRACEFUL_OR_EXITED"
    except (OSError, subprocess.TimeoutExpired):
        return "CLEANUP_NOT_VERIFIED"
    finally:
        for stream in (proc.stdin, proc.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def _drive_app_server(*, command: list[str], cwd: str, mode: str,
                      timeout_seconds: float, env: dict[str, str]) -> dict[str, Any]:
    """Внутренняя функция; произвольный command недоступен внешнему CLI."""
    if mode not in ("initialize", "thread"):
        raise SafeProtocolError("UNSUPPORTED_MODE")
    if not 1 <= timeout_seconds <= 45:
        raise SafeProtocolError("BAD_TIMEOUT")
    try:
        allowed_workspace = Path(cwd).resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise SafeProtocolError("BAD_WORKSPACE") from exc
    if not allowed_workspace.is_dir() or allowed_workspace.is_symlink():
        raise SafeProtocolError("BAD_WORKSPACE")

    start = time.monotonic()
    report: dict[str, Any] = {
        "schema": "RAI_FABRIC_CODEX_REAL_TRANSPORT/1",
        "status": "BLOCKED", "code": "NOT_STARTED", "stage": "spawn",
        "mode": mode, "initialize_response": False, "initialized_sent": False,
        "thread_created": False, "thread_id_sha256_prefix": None,
        "method_names_sent": [], "notification_count": 0, "frames_received": 0,
        "no_turn_start_sent": True, "no_oauth_performed": True,
        "rpc_error_code": None,  # Только ограниченный числовой код, не сообщение сервера.
        "no_api_key_in_child_env": not any(k.upper().endswith("API_KEY") for k in env),
        "child_cleanup": "NOT_STARTED", "duration_ms": None,
    }
    received: queue.Queue[object] = queue.Queue(maxsize=_MAX_MESSAGES + 4)
    child: subprocess.Popen[bytes] | None = None
    reader: threading.Thread | None = None
    deadline = start + timeout_seconds

    def send(msg: dict[str, Any]) -> None:
        data = json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        if len(data) > _MAX_LINE:
            raise SafeProtocolError("OUTBOUND_RPC_TOO_LARGE")
        if child is None or child.stdin is None:
            raise SafeProtocolError("CHILD_STDIN_UNAVAILABLE")
        child.stdin.write(data)
        child.stdin.flush()
        report["method_names_sent"].append(msg["method"])

    def consume(rpc_id: int) -> dict[str, Any]:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SafeProtocolError("RPC_TIMEOUT")
            try:
                raw = received.get(timeout=remaining)
            except queue.Empty as exc:
                raise SafeProtocolError("RPC_TIMEOUT") from exc
            if raw is _EOF:
                raise SafeProtocolError("CHILD_STDOUT_EOF")
            if isinstance(raw, Exception):
                raise SafeProtocolError("CHILD_STDOUT_READ_FAILED")
            assert isinstance(raw, bytes)
            report["frames_received"] += 1
            if report["frames_received"] > _MAX_MESSAGES:
                raise SafeProtocolError("TOO_MANY_FRAMES")
            msg = _parse_response(raw)
            if "method" in msg and "id" in msg:
                raise SafeProtocolError("SERVER_REQUEST_REQUIRES_MANUAL_HANDLING")
            if "id" not in msg:
                if not isinstance(msg.get("method"), str):
                    raise SafeProtocolError("UNEXPECTED_RPC_MESSAGE")
                report["notification_count"] += 1
                continue
            if type(msg["id"]) is not int or msg["id"] != rpc_id:
                raise SafeProtocolError("UNEXPECTED_RPC_ID")
            if "error" in msg:
                rpc_error = msg["error"]
                numeric = rpc_error.get("code") if isinstance(rpc_error, dict) else None
                # Сохраняем только ограниченный числовой код; исключаем bool и
                # любые произвольные строки/error.data из публичной диагностики.
                if type(numeric) is int and -1000000 <= numeric <= 1000000:
                    report["rpc_error_code"] = numeric
                raise SafeProtocolError("RPC_ERROR_FROM_SERVER")
            result = msg.get("result")
            if not isinstance(result, dict):
                raise SafeProtocolError("INVALID_RPC_RESULT")
            return result

    try:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        child = subprocess.Popen(command, cwd=str(allowed_workspace), env=env,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, shell=False,
                                 creationflags=creationflags)
        assert child.stdout is not None

        def collect() -> None:
            try:
                while True:
                    line = child.stdout.readline(_MAX_LINE + 1)
                    if not line:
                        break
                    try:
                        received.put(line, timeout=0.2)
                    except queue.Full:
                        break
                    if len(line) > _MAX_LINE:
                        break
            except Exception as e:
                try:
                    received.put(e, timeout=0.2)
                except queue.Full:
                    pass
            finally:
                try:
                    received.put(_EOF, timeout=0.2)
                except queue.Full:
                    pass

        reader = threading.Thread(target=collect, daemon=True, name="raif-codex-stdio")
        reader.start()
        report["stage"] = "initialize"
        send({"method": "initialize", "id": 1, "params": {
            "clientInfo": {"name": "rassvet_ai_fabric", "title": "Rassvet AI Fabric", "version": "0.1.0"},
            "capabilities": {"experimentalApi": False}}})
        consume(1)
        report["initialize_response"] = True
        send({"method": "initialized"})
        report["initialized_sent"] = True
        if mode == "thread":
            report["stage"] = "thread_start"
            send({"method": "thread/start", "id": 2, "params": {
                "model": None, "cwd": str(allowed_workspace),
                "sandbox": "read-only", "approvalPolicy": "never",
                "ephemeral": True, "serviceName": "rassvet_ai_fabric"}})
            response = consume(2)
            thread_obj = response.get("thread")
            thread_id = thread_obj.get("id") if isinstance(thread_obj, dict) else None
            if not isinstance(thread_id, str) or not thread_id.strip() or len(thread_id) > 256:
                raise SafeProtocolError("THREAD_ID_MISSING_OR_INVALID")
            report["thread_created"] = True
            report["thread_id_sha256_prefix"] = hashlib.sha256(thread_id.encode()).hexdigest()[:16]
        report["status"] = "PASS_WITH_SCOPE"
        report["code"] = "THREAD_CREATED_NO_TURN" if mode == "thread" else "INITIALIZED_NO_TURN"
        report["stage"] = "complete"
    except SafeProtocolError as exc:
        report["code"] = exc.code
    except (OSError, ValueError, BrokenPipeError, subprocess.SubprocessError):
        report["code"] = "CHILD_PROCESS_OR_IO_ERROR"
    finally:
        report["child_cleanup"] = _cleanup(child)
        if reader is not None:
            reader.join(timeout=1.0)
        if report["child_cleanup"] == "CLEANUP_NOT_VERIFIED":
            report["status"] = "BLOCKED"
            report["code"] = "CLEANUP_NOT_VERIFIED"
        report["duration_ms"] = round((time.monotonic() - start) * 1000)
    return report


def probe_installed_codex(*, binary: str | Path, workspace: str | Path,
                          mode: str = "thread", timeout_seconds: float = 18.0,
                          expected_sha256: str | None = None) -> dict[str, Any]:
    """Публичная точка входа: запускает только проверенный codex.exe, без turn/start."""
    allowed = _owns_binary(binary)
    if os.name == "nt":
        # Диагностический режим не может смотреть чужие рабочие проекты.
        try:
            scratch = Path(workspace).resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise SafeProtocolError("PROBE_WORKSPACE_NOT_ISOLATED") from exc
        if (not scratch.is_dir() or scratch.name.casefold() != "workspace" or
                "_raif_runtime" not in (part.casefold() for part in scratch.parts)):
            raise SafeProtocolError("PROBE_WORKSPACE_NOT_ISOLATED")
    if expected_sha256 is not None:
        if len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256.lower()):
            raise SafeProtocolError("INVALID_EXPECTED_BINARY_HASH")
        digest = hashlib.sha256()
        with allowed.open("rb") as binary_file:
            while chunk := binary_file.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest().lower() != expected_sha256.lower():
            raise SafeProtocolError("CODEX_BINARY_HASH_CHANGED")
    with tempfile.TemporaryDirectory(prefix="raif-private-codex-home-") as home:
        return _drive_app_server(command=[str(allowed), "app-server", "--listen", "stdio://"],
                                cwd=str(workspace), mode=mode, timeout_seconds=timeout_seconds,
                                env=_environment(home))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rassvet AI Fabric: изолированный Codex App Server без модели")
    parser.add_argument("--binary", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--mode", choices=["initialize", "thread"], default="thread")
    parser.add_argument("--timeout", type=float, default=18.0)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args(argv)
    try:
        result = probe_installed_codex(binary=args.binary, workspace=args.workspace,
                                       mode=args.mode, timeout_seconds=args.timeout,
                                       expected_sha256=args.expected_sha256)
    except (SafeProtocolError, OSError, ValueError) as exc:
        result = {"schema": "RAI_FABRIC_CODEX_REAL_TRANSPORT/1", "status": "BLOCKED",
                  "code": exc.code if isinstance(exc, SafeProtocolError) else "PROBE_INPUT_ERROR",
                  "mode": args.mode, "no_turn_start_sent": True, "no_oauth_performed": True}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS_WITH_SCOPE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
