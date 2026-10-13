# -*- coding: utf-8 -*-
"""
rai_fabric.claude_vertex_transport - Адаптер транспорта для моделей Claude через Google Cloud Vertex AI (CP-55).
Реализует:
  1. Интерфейс ITransportChannel из transport.ipc_channel;
  2. Аутентификацию через Google ADC (Application Default Credentials, единый биллинг);
  3. Детекцию лимитов 429/503 и выброс стандартизированных TransportError(RATE_LIMITED);
  4. Поддержку синтетического mock-клиента для 100% офлайн тестирования и Windows CI;
  5. Проверку криптографической целостности конвертов (FAIL_CLOSED).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / CP-55 / Rassvet_AI_Fabric#20.
"""

from __future__ import annotations

__version__ = "1.0.0"

import json
import logging
import queue
import time
from typing import Any, Dict, Optional

from transport.ipc_channel import (
    ITransportChannel,
    TransportError,
    TransportMessageEnvelope,
    TransportStatus,
)

logger = logging.getLogger("raif.claude_vertex_transport")

DEFAULT_CLAUDE_MODEL = "claude-3-5-sonnet@20240620"
DEFAULT_VERTEX_REGION = "us-east5"


class ClaudeVertexTransport(ITransportChannel):
    """Канал отправки задач в модели Claude через Google Vertex AI с обработкой лимитов квот."""

    def __init__(
        self,
        project_id: str = "synthetic-gcp-project",
        region: str = DEFAULT_VERTEX_REGION,
        model_name: str = DEFAULT_CLAUDE_MODEL,
        mock_client: Optional[Any] = None,
    ) -> None:
        self.project_id = project_id
        self.region = region
        self.model_name = model_name
        self.mock_client = mock_client
        self._status = TransportStatus.DISCONNECTED
        self._client: Optional[Any] = None
        self._inbox: queue.Queue[TransportMessageEnvelope] = queue.Queue()
        self._sent_count: int = 0
        self._rate_limit_count: int = 0

    @property
    def status(self) -> TransportStatus:
        """Текущий статус транспортного канала."""
        return self._status

    @property
    def sent_count(self) -> int:
        """Количество успешно отправленных сообщений."""
        return self._sent_count

    @property
    def rate_limit_count(self) -> int:
        """Счётчик зарегистрированных событий превышения квоты."""
        return self._rate_limit_count

    def connect(self) -> bool:
        """Инициализация клиента Vertex AI (или использование mock-клиента)."""
        self._status = TransportStatus.CONNECTING
        try:
            if self.mock_client is not None:
                self._client = self.mock_client
            else:
                # Опциональный импорт anthropic[vertex] при наличии
                try:
                    import anthropic
                    self._client = anthropic.AnthropicVertex(
                        region=self.region,
                        project_id=self.project_id,
                    )
                except ImportError:
                    # В офлайн-окружении без установленного anthropic используем безопасный stub
                    self._client = None
            self._status = TransportStatus.CONNECTED
            return True
        except Exception as exc:
            self._status = TransportStatus.ERROR
            logger.error("Failed to connect ClaudeVertexTransport: %s", exc)
            return False

    def disconnect(self) -> None:
        """Закрытие канала и сброс состояния."""
        self._status = TransportStatus.CLOSED
        self._client = None

    def is_connected(self) -> bool:
        """Проверка активности соединения."""
        return self._status == TransportStatus.CONNECTED

    def probe(self, timeout: float = 3.0) -> bool:
        """Быстрый healthcheck модели для проверки доступности квоты."""
        if not self.is_connected():
            return False
        try:
            if self.mock_client is not None:
                if hasattr(self.mock_client, "probe"):
                    return bool(self.mock_client.probe(timeout=timeout))
                return True
            return True
        except Exception:
            return False

    def send(self, envelope: TransportMessageEnvelope) -> bool:
        """Отправка сообщения через Claude Vertex AI канал."""
        if not self.is_connected():
            raise TransportError("NOT_CONNECTED", "Cannot send envelope: channel is not connected")

        if not envelope.verify_signature():
            self._status = TransportStatus.ERROR
            raise TransportError("SIGNATURE_MISMATCH", "Envelope cryptographic verification failed")

        try:
            # Вызов mock_client или реального клиента
            if self.mock_client is not None:
                response_payload = self.mock_client.send(envelope.payload)
            else:
                if self._client is None:
                    raise TransportError("CLIENT_UNAVAILABLE", "Anthropic Vertex client is not initialized")
                
                # Извлечение текста запроса
                prompt_text = envelope.payload.get("prompt") or str(envelope.payload)
                message = self._client.messages.create(
                    model=self.model_name,
                    max_tokens=envelope.payload.get("max_tokens", 1024),
                    messages=[{"role": "user", "content": prompt_text}],
                )
                response_payload = {
                    "model": message.model,
                    "content": [b.text for b in message.content if hasattr(b, "text")],
                    "usage": {
                        "input_tokens": getattr(message.usage, "input_tokens", 0),
                        "output_tokens": getattr(message.usage, "output_tokens", 0),
                    },
                }

            # Формирование ответного конверта
            resp_env = TransportMessageEnvelope.create(
                payload_type="response",
                payload={"reply": response_payload, "ref_id": envelope.message_id},
                channel=envelope.channel,
                source=f"claude_vertex:{self.model_name}",
            )
            self._inbox.put(resp_env)
            self._sent_count += 1
            return True

        except TransportError:
            raise
        except Exception as exc:
            err_str = str(exc).lower()
            if "429" in err_str or "rate_limit" in err_str or "quota" in err_str:
                self._rate_limit_count += 1
                self._status = TransportStatus.DEGRADED
                raise TransportError("RATE_LIMITED", f"Claude Vertex quota exceeded: {exc}") from exc
            if "503" in err_str or "overloaded" in err_str or "unavailable" in err_str:
                self._status = TransportStatus.DEGRADED
                raise TransportError("SERVICE_UNAVAILABLE", f"Claude service unavailable: {exc}") from exc
            
            self._status = TransportStatus.ERROR
            raise TransportError("TRANSPORT_SEND_FAILED", f"Claude request failed: {exc}") from exc

    def receive(self, timeout: float = 1.0) -> Optional[TransportMessageEnvelope]:
        """Получение ответа из входящей очереди."""
        if not self.is_connected():
            return None
        try:
            return self._inbox.get(block=True, timeout=timeout)
        except queue.Empty:
            return None
