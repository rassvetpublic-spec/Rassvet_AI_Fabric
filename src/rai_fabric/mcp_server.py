"""MCP-сервер по stdio: только чтение, согласование протокола 2025-11-25."""
from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .gateway import Gateway, tools_manifest
from .store import FabricError

SUPPORTED = {"2025-11-25", "2025-06-18"}
MAX_MESSAGE_BYTES = 4 * 1024 * 1024


class MCPStdioServer:
    def __init__(self, gateway: Gateway):
        self.gateway = gateway
        self.initialized = False

    @staticmethod
    def _result(req_id: Any, data: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": data}

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": code, "message": message}}

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self._error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Некорректный запрос")
        method = msg.get("method")
        if not isinstance(method, str):
            return self._error(msg.get("id"), -32600, "Некорректный метод")
        if method.startswith("notifications/"):
            # На уведомления MCP ответ не отправляется.
            return None
        req_id = msg.get("id")
        if req_id is None:
            return self._error(None, -32600, "У запроса должен быть идентификатор id")
        if method == "initialize":
            params = msg.get("params") or {}
            if not isinstance(params, dict):
                return self._error(req_id, -32602, "Некорректные параметры инициализации")
            version = params.get("protocolVersion")
            self.initialized = True
            return self._result(req_id, {"protocolVersion": version if version in SUPPORTED else "2025-11-25",
                                         "capabilities": {"tools": {"listChanged": False}},
                                         "serverInfo": {"name": "rassvet-ai-fabric", "version": "0.1.0"},
                                         "instructions": "Доступ только для чтения. Изменение состояния возможно лишь через локальный CLI с явным разрешением."})
        if not self.initialized:
            return self._error(req_id, -32000, "Сначала инициализируйте соединение MCP")
        if method == "ping":
            return self._result(req_id, {})
        if method == "tools/list":
            return self._result(req_id, {"tools": tools_manifest()})
        if method == "tools/call":
            params = msg.get("params")
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return self._error(req_id, -32602, "Некорректные аргументы инструмента")
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                return self._error(req_id, -32602, "Аргументы инструмента должны быть объектом JSON")
            names = {tool["name"] for tool in tools_manifest()}
            if params["name"] not in names:
                return self._error(req_id, -32602, "Неизвестный инструмент")
            try:
                value = self.gateway.invoke(params["name"], args)
                output = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                          "isError": False}
            except (FabricError, ValueError, OSError, KeyError, TypeError, UnicodeDecodeError) as exc:
                output = {"content": [{"type": "text", "text": f"{type(exc).__name__}: {str(exc)[:300]}"}],
                          "isError": True}
            return self._result(req_id, output)
        return self._error(req_id, -32601, f"Метод не найден: {method}")

    def serve(self, input_stream: TextIO | None = None, output_stream: TextIO | None = None) -> None:
        in_stream = input_stream or sys.stdin
        out_stream = output_stream or sys.stdout
        for line in in_stream:
            if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
                print("Размер входящего сообщения MCP превышает ограничение", file=sys.stderr)
                continue
            try:
                msg = json.loads(line)
                response = self.handle(msg)
            except (json.JSONDecodeError, UnicodeError) as exc:
                response = self._error(None, -32700, f"Ошибка разбора JSON: {exc}")
            if response is not None:
                out_stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
                out_stream.flush()
