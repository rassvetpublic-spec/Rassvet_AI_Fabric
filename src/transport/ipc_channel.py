# -*- coding: utf-8 -*-
"""
transport.ipc_channel - Интерфейсы и канонические структуры данных реального IPC-транспорта RAiF.
Определяет:
  1. Контракт конверта сообщений TransportMessageEnvelope с SHA-256 подписью;
  2. Базовый абстрактный интерфейс ITransportChannel;
  3. Типы полезной нагрузки (JSON-RPC, телеметрия, heartbeat, команды);
  4. Стандартизированные статусы и обработку ошибок (fail-closed).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.2) / RAiF 10.7 Stage R25 / Rassvet_AI_Fabric#15.
"""

from __future__ import annotations

__version__ = "1.0.0"

import abc
import enum
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class TransportStatus(str, enum.Enum):
    """Статусы жизненного цикла транспортного канала."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    DEGRADED = "DEGRADED"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


class TransportError(Exception):
    """Исключение транспортного уровня с кодом ошибки без утечки внутренних секретов."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


def _canonical_json(value: Any) -> str:
    """Детерминированная сериализация в компактный JSON со стабильным порядком ключей."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    """Вычисление SHA-256 дайджеста текстовой строки."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    """Текущее время в формате ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TransportMessageEnvelope:
    """Канонический конверт сообщения IPC-транспорта с целостной SHA-256 подписью."""

    message_id: str
    timestamp: str
    channel: str
    payload_type: str  # "json_rpc", "command", "telemetry", "heartbeat", "response", "error"
    payload: Dict[str, Any]
    source: str = "raif_transport"
    signature: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)

    def calculate_signature(self) -> str:
        """Вычисляет детерминированный SHA-256 дайджест содержимого пакета."""
        core_repr = {
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "channel": self.channel,
            "payload_type": self.payload_type,
            "payload": self.payload,
            "source": self.source,
        }
        return _sha256_text(_canonical_json(core_repr))

    def sign(self) -> str:
        """Генерирует и сохраняет цифровую подпись конверта."""
        sig = self.calculate_signature()
        self.signature = sig
        return sig

    def verify_signature(self) -> bool:
        """Проверяет соответствие цифровой подписи фактическому содержимому."""
        if not self.signature:
            return False
        return self.calculate_signature().lower() == self.signature.lower()

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование конверта в словарь для передачи по сети/каналу."""
        if not self.signature:
            self.sign()
        return {
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "channel": self.channel,
            "payload_type": self.payload_type,
            "payload": self.payload,
            "source": self.source,
            "signature": self.signature,
            "headers": self.headers,
        }

    def to_json(self) -> str:
        """Преобразование в строку JSON."""
        return _canonical_json(self.to_dict())

    def to_bytes(self) -> bytes:
        """Преобразование в байты UTF-8."""
        return self.to_json().encode("utf-8")

    @classmethod
    def from_dict(cls, data: Dict[str, Any], verify: bool = True) -> TransportMessageEnvelope:
        """Восстановление конверта из словаря с опциональной валидацией подписи."""
        if not isinstance(data, dict):
            raise TransportError("INVALID_ENVELOPE_FORMAT", "Envelope must be a dict")
        for req in ("message_id", "timestamp", "channel", "payload_type", "payload"):
            if req not in data:
                raise TransportError("MISSING_ENVELOPE_FIELD", f"Missing required field: {req}")

        envelope = cls(
            message_id=str(data["message_id"]),
            timestamp=str(data["timestamp"]),
            channel=str(data["channel"]),
            payload_type=str(data["payload_type"]),
            payload=dict(data["payload"]) if isinstance(data["payload"], dict) else {"data": data["payload"]},
            source=str(data.get("source", "unknown")),
            signature=data.get("signature"),
            headers=dict(data.get("headers", {})),
        )
        if verify and envelope.signature is not None:
            if not envelope.verify_signature():
                raise TransportError("SIGNATURE_MISMATCH", "Envelope signature verification failed")
        return envelope

    @classmethod
    def from_json(cls, raw: str | bytes, verify: bool = True) -> TransportMessageEnvelope:
        """Восстановление конверта из строки или байт JSON."""
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
            return cls.from_dict(data, verify=verify)
        except json.JSONDecodeError as exc:
            raise TransportError("JSON_DECODE_ERROR", str(exc)) from exc

    @classmethod
    def create(
        cls,
        payload_type: str,
        payload: Dict[str, Any],
        channel: str = "raif_transport",
        source: str = "raif_transport",
        headers: Optional[Dict[str, str]] = None,
    ) -> TransportMessageEnvelope:
        """Фабричный метод создания нового подписанного конверта."""
        msg_id = f"msg_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        envelope = cls(
            message_id=msg_id,
            timestamp=_utc_now_iso(),
            channel=channel,
            payload_type=payload_type,
            payload=payload,
            source=source,
            headers=headers or {},
        )
        envelope.sign()
        return envelope


class ITransportChannel(abc.ABC):
    """Абстрактный базовый интерфейс двунаправленного транспортного канала."""

    @property
    @abc.abstractmethod
    def status(self) -> TransportStatus:
        """Текущий статус канала."""
        raise NotImplementedError

    @abc.abstractmethod
    def connect(self) -> bool:
        """Установление соединения. Возвращает True при успехе."""
        raise NotImplementedError

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Закрытие соединения и освобождение ресурсов."""
        raise NotImplementedError

    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Проверка активности соединения."""
        raise NotImplementedError

    @abc.abstractmethod
    def send(self, envelope: TransportMessageEnvelope) -> bool:
        """Отправка конверта. Возвращает True при подтверждённой доставке в сокет/буфер."""
        raise NotImplementedError

    @abc.abstractmethod
    def receive(self, timeout: float = 1.0) -> Optional[TransportMessageEnvelope]:
        """Приём очередного конверта сообщений с заданным тайм-аутом в секундах."""
        raise NotImplementedError
