"""Подставной процесс App Server для офлайн-интеграционных тестов.

Внимание: НЕ настоящий Codex, не читает авторизацию и не отправляет запросы в сеть.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any


def _send(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальный подставной Codex App Server без модели")
    parser.add_argument("--scenario", choices=["success", "failed", "approval", "timeout", "eof"],
                        default="success")
    args = parser.parse_args()
    initialized = False
    thread_started = False
    for raw in sys.stdin:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(message, dict):
            return
        method = message.get("method")
        if method == "initialize" and "id" in message:
            _send({"id": message["id"], "result": {"userAgent": "rai-mock-server/1"}})
        elif method == "initialized":
            initialized = True
        elif method == "thread/start" and "id" in message and initialized:
            _send({"method": "thread/started", "params": {"thread": {"id": "mock-thread"}}})
            _send({"id": message["id"], "result": {"thread": {"id": "mock-thread"}}})
            thread_started = True
        elif method == "turn/start" and "id" in message and thread_started:
            _send({"id": message["id"], "result": {"turn": {"id": "mock-turn"}}})
            if args.scenario == "eof":
                return
            if args.scenario == "timeout":
                time.sleep(15)
                return
            if args.scenario == "approval":
                _send({"id": 8101, "method": "item/commandExecution/requestApproval",
                       "params": {"threadId": "mock-thread", "turnId": "mock-turn"}})
                time.sleep(15)
                return
            if args.scenario == "success":
                for delta in ("Подставной ", "ответ получен"):
                    _send({"method": "item/agentMessage/delta",
                           "params": {"threadId": "mock-thread", "turnId": "mock-turn", "delta": delta}})
            _send({"method": "turn/completed", "params": {"threadId": "mock-thread",
                   "turnId": "mock-turn", "turn": {"status": "completed" if args.scenario == "success" else "failed"}}})
            return
        elif method not in ("initialize", "initialized", "thread/start", "turn/start"):
            return


if __name__ == "__main__":
    main()
