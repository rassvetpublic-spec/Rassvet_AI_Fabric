"""Офлайн-контракт обмена с Codex App Server: не запускает процессы и модели.

Это проверяемое описание последовательности JSON-RPC. Отдельный транспорт и
безопасный OAuth-клиент будут добавлены только после независимой приёмки.
"""
from __future__ import annotations

import json
from typing import Any

from .store import FabricError


_MAX_INCOMING_BYTES = 262144
_MAX_OUTPUT_CHARS = 65536


class CodexProtocolError(FabricError):
    """Неверная последовательность, повреждённое сообщение либо запрос разрешения."""


class CodexAppProtocol:
    """Контролирует один поток и один turn; без доступа к сетевым и локальным ресурсам."""

    def __init__(self, name: str = "rassvet_ai_fabric", title: str = "Rassvet AI Fabric",
                 version: str = "0.1.0") -> None:
        if not all(isinstance(s, str) and 0 < len(s) <= 128 for s in (name, title, version)):
            raise CodexProtocolError("Неверные сведения о клиентском приложении")
        self.client_info = {"name": name, "title": title, "version": version}
        self.state = "NEW"
        self.thread_id: str | None = None
        self.turn_id: str | None = None
        self._pending: tuple[int, str] | None = None
        self._next_id = 1
        self._parts: list[str] = []
        self._output_size = 0
        self.verdict: str | None = None
        self.cursor = "INITIALIZE"
        self.error_code: str | None = None

    @staticmethod
    def decode_line(raw: bytes) -> dict[str, Any]:
        """Принимает одну строку JSON в UTF-8 и ограничивает размер пакета."""
        if not isinstance(raw, bytes) or len(raw) > _MAX_INCOMING_BYTES:
            raise CodexProtocolError("Размер входного JSON-RPC сообщения недопустим")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexProtocolError("Повреждённая строка JSON-RPC") from exc
        if not isinstance(parsed, dict):
            raise CodexProtocolError("JSON-RPC сообщение должно быть объектом")
        return parsed

    def _request(self, method: str, params: dict[str, Any], state: str) -> dict[str, Any]:
        if self._pending is not None:
            raise CodexProtocolError("Предыдущий запрос ещё не подтверждён")
        msg_id = self._next_id
        self._next_id += 1
        self._pending = (msg_id, method)
        self.state = state
        return {"method": method, "id": msg_id, "params": params}

    def initialize(self) -> dict[str, Any]:
        if self.state != "NEW":
            raise CodexProtocolError("Повторный initialize запрещён")
        return self._request("initialize", {"clientInfo": self.client_info}, "WAIT_INITIALIZE")

    def initialized(self) -> dict[str, Any]:
        if self.state != "READY_TO_ACK":
            raise CodexProtocolError("Уведомление initialized допустимо только после initialize")
        self.state = "READY"
        self.cursor = "THREAD_START"
        return {"method": "initialized", "params": {}}

    def thread_start(self, *, model: str, cwd: str) -> dict[str, Any]:
        if self.state != "READY":
            raise CodexProtocolError("Сначала требуется завершить инициализацию")
        if not isinstance(model, str) or not model.strip() or len(model) > 128:
            raise CodexProtocolError("Требуется явно выбранная модель")
        if not isinstance(cwd, str) or not cwd.strip() or len(cwd) > 2048:
            raise CodexProtocolError("Рабочий каталог не указан")
        # readOnly исключает запись до проверки отдельного контракта разрешений.
        return self._request("thread/start", {
            "model": model, "cwd": cwd, "approvalPolicy": "unlessTrusted",
            "sandbox": "readOnly", "serviceName": "rassvet_ai_fabric"
        }, "WAIT_THREAD")

    def turn_start(self, prompt: str) -> dict[str, Any]:
        if self.state != "THREAD_READY" or not self.thread_id:
            raise CodexProtocolError("Отсутствует подтверждённый поток Codex")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 65536:
            raise CodexProtocolError("Текст задачи пуст или превышает лимит")
        self._parts.clear()
        self._output_size = 0
        return self._request("turn/start", {
            "threadId": self.thread_id,
            "input": [{"type": "text", "text": prompt}]
        }, "WAIT_TURN")

    def _block(self, cursor: str, error_code: str = "PROTOCOL_BLOCKED") -> dict[str, Any]:
        self.state = "BLOCKED"
        self.verdict = "BLOCKED"
        self.cursor = cursor
        self.error_code = error_code
        self._pending = None
        return {"verdict": self.verdict, "cursor": self.cursor, "error_code": error_code}

    def _ensure_identity(self, params: dict[str, Any]) -> None:
        if params.get("threadId") != self.thread_id or params.get("turnId") != self.turn_id:
            self._block("VERIFY_EVENT_IDENTITY", "EVENT_IDENTITY_MISMATCH")
            raise CodexProtocolError("Событие принадлежит другому потоку или выполнению")

    def consume(self, message: dict[str, Any] | bytes) -> dict[str, Any] | None:
        """Нормализует ответ/событие. Никогда не выдаёт автоматическое одобрение."""
        if isinstance(message, bytes):
            message = self.decode_line(message)
        if not isinstance(message, dict):
            raise CodexProtocolError("Некорректное сообщение Codex")
        if self.state in ("BLOCKED", "COMPLETE"):
            raise CodexProtocolError("Поток уже завершён или заблокирован")

        method = message.get("method")
        if "id" in message and method is not None:
            # Запрос от сервера, в том числе на исполнение команд/разрешения.
            return self._block("MANUAL_SERVER_REQUEST", "SERVER_REQUEST_REQUIRES_APPROVAL")

        if "id" in message:
            if not self._pending or message["id"] != self._pending[0]:
                return self._block("VERIFY_RPC_RESPONSE", "UNEXPECTED_RESPONSE_ID")
            pending_method = self._pending[1]
            self._pending = None
            error = message.get("error")
            if error is not None:
                code = error.get("code") if isinstance(error, dict) else "UNKNOWN"
                return self._block("VERIFY_RPC_ERROR", str(code)[:64])
            result = message.get("result")
            if not isinstance(result, dict):
                return self._block("VERIFY_RPC_RESULT", "INVALID_RPC_RESULT")
            if pending_method == "initialize" and self.state == "WAIT_INITIALIZE":
                self.state = "READY_TO_ACK"
                self.cursor = "INITIALIZED"
                return {"action": "INITIALIZE_ACK_REQUIRED"}
            if pending_method == "thread/start" and self.state == "WAIT_THREAD":
                thread = result.get("thread")
                identifier = thread.get("id") if isinstance(thread, dict) else None
                if not isinstance(identifier, str) or not identifier:
                    return self._block("VERIFY_THREAD_ID", "MISSING_THREAD_ID")
                self.thread_id = identifier
                self.state = "THREAD_READY"
                self.cursor = "TURN_START"
                return {"thread_id": identifier, "cursor": self.cursor}
            if pending_method == "turn/start" and self.state == "WAIT_TURN":
                turn = result.get("turn")
                identifier = turn.get("id") if isinstance(turn, dict) else None
                if not isinstance(identifier, str) or not identifier:
                    return self._block("VERIFY_TURN_ID", "MISSING_TURN_ID")
                self.turn_id = identifier
                self.state = "RUNNING"
                self.cursor = "TURN_COMPLETED_EVENT"
                return {"turn_id": identifier, "cursor": self.cursor}
            return self._block("VERIFY_RPC_ORDER", "RPC_OUT_OF_ORDER")

        if not isinstance(method, str):
            return self._block("VERIFY_NOTIFICATION", "UNKNOWN_NOTIFICATION")
        if method == "item/agentMessage/delta":
            if self.state != "RUNNING":
                return self._block("VERIFY_DELTA_ORDER", "DELTA_OUT_OF_ORDER")
            params = message.get("params")
            if not isinstance(params, dict):
                return self._block("VERIFY_DELTA", "INVALID_DELTA")
            self._ensure_identity(params)
            delta = params.get("delta")
            if not isinstance(delta, str):
                return self._block("VERIFY_DELTA", "INVALID_DELTA")
            if self._output_size + len(delta) > _MAX_OUTPUT_CHARS:
                return self._block("VERIFY_OUTPUT_LIMIT", "OUTPUT_TOO_LARGE")
            self._parts.append(delta)
            self._output_size += len(delta)
            return {"delta_chars": len(delta)}
        if method == "turn/completed":
            if self.state != "RUNNING":
                return self._block("VERIFY_COMPLETION_ORDER", "COMPLETION_OUT_OF_ORDER")
            params = message.get("params")
            if not isinstance(params, dict):
                return self._block("VERIFY_COMPLETION", "INVALID_COMPLETION")
            self._ensure_identity(params)
            turn = params.get("turn")
            status = turn.get("status") if isinstance(turn, dict) else None
            if status == "completed":
                self.state = "COMPLETE"
                self.verdict = "PASS"
                self.cursor = "REVIEW_EVIDENCE"
                return {"verdict": self.verdict, "cursor": self.cursor,
                        "output_chars": self._output_size}
            return self._block("VERIFY_EXTERNAL_SIDE_EFFECTS", "TURN_NOT_COMPLETED")
        # Другие уведомления не служат доказательством окончания работы.
        return None

    def result(self) -> dict[str, Any]:
        return {"state": self.state, "verdict": self.verdict, "cursor": self.cursor,
                "thread_id": self.thread_id, "turn_id": self.turn_id,
                "response": "".join(self._parts) if self.state == "COMPLETE" else None,
                "error_code": self.error_code}
