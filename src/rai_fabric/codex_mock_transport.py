"""Офлайн-stdio транспорт к подставному процессу Codex App Server.

Транспорт намеренно не может запускать настоящий Codex или использовать токены.
Реальный разрешённый клиент требует отдельного внешнего интерфейса.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .codex_protocol import CodexAppProtocol, CodexProtocolError


_EOF = object()
_MAX_MESSAGES = 200


def _safe_mock_environment() -> dict[str, str]:
    """Дочерний процесс получает только необходимую среду без секретов."""
    approved = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "TEMP", "TMP", "TMPDIR")
    env = {key: os.environ[key] for key in approved if key in os.environ}
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_codex_mock(*, scenario: str = "success", timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Исполняет полный протокол через stdio локального имитатора, без подписки."""
    if scenario not in {"success", "failed", "approval", "timeout", "eof"}:
        raise CodexProtocolError("Неизвестный сценарий подставного процесса")
    if not (isinstance(timeout_seconds, (float, int)) and 0.05 <= timeout_seconds <= 30):
        raise CodexProtocolError("Недопустимая длительность тестового запуска")

    session = CodexAppProtocol()
    deadline = time.monotonic() + float(timeout_seconds)
    incoming: queue.Queue[bytes | object] = queue.Queue(maxsize=_MAX_MESSAGES)
    child = subprocess.Popen(
        [sys.executable, "-I", "-X", "utf8", "-B",
         str(Path(__file__).resolve().with_name("codex_mock_server.py")), "--scenario", scenario],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=_safe_mock_environment(), shell=False,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    assert child.stdin is not None and child.stdout is not None

    def reader() -> None:
        try:
            while True:
                raw = child.stdout.readline(262145)
                if not raw:
                    break
                try:
                    incoming.put(raw, timeout=0.5)
                except queue.Full:
                    break
        finally:
            try:
                incoming.put(_EOF, timeout=0.5)
            except queue.Full:
                pass

    thread = threading.Thread(target=reader, name="codex-mock-stdio-reader", daemon=True)
    thread.start()
    nreceived = 0

    def send(message: dict[str, Any]) -> None:
        import json
        assert child.stdin is not None
        data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(data) > 262144:
            raise CodexProtocolError("Слишком крупный исходящий RPC-пакет")
        child.stdin.write(data)
        child.stdin.flush()

    def until(states: set[str]) -> None:
        nonlocal nreceived
        while session.state not in states:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Превышено время ожидания App Server")
            try:
                raw = incoming.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError("Превышено время ожидания App Server") from exc
            if raw is _EOF:
                raise EOFError("Процесс завершился без обязательного события")
            nreceived += 1
            if nreceived > _MAX_MESSAGES:
                raise CodexProtocolError("Слишком много уведомлений от процесса")
            session.consume(raw)

    try:
        send(session.initialize())
        until({"READY_TO_ACK", "BLOCKED"})
        if session.state == "BLOCKED":
            return session.result()
        send(session.initialized())
        send(session.thread_start(model="model-for-offline-test", cwd=str(Path(__file__).resolve().parents[2])))
        until({"THREAD_READY", "BLOCKED"})
        if session.state == "BLOCKED":
            return session.result()
        send(session.turn_start("Проверка связи по stdio без модели"))
        until({"COMPLETE", "BLOCKED"})
        return session.result()
    except (TimeoutError, EOFError, BrokenPipeError, OSError, CodexProtocolError) as exc:
        if session.state != "BLOCKED":
            if isinstance(exc, TimeoutError):
                session._block("VERIFY_PROCESS_TIMEOUT", "PROCESS_TIMEOUT")
            elif isinstance(exc, EOFError):
                session._block("VERIFY_PROCESS_EXIT", "PROCESS_EOF")
            else:
                session._block("VERIFY_PROCESS_FAILURE", type(exc).__name__.upper())
        return session.result()
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        for stream in (child.stdin, child.stdout):
            if stream:
                stream.close()
        thread.join(timeout=1)
