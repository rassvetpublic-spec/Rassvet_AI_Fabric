# -*- coding: utf-8 -*-
"""
rai_fabric.failover_router - Автономный отказоустойчивый роутер запросов с каскадным переключением (CP-55).
Реализует:
  1. Маршрутизацию запросов: Primary (Gemini) -> Fallback (Claude Haiku) -> Escalation (Claude Sonnet);
  2. Защиту от зацикливаний и лимит попыток (retry_budget);
  3. Автоматический возврат на основную модель при восстановлении квоты (RETURN_TO_PRIMARY_ON_RECOVERY);
  4. Нулевой износ накопителя (Zero SSD Wear) через фиксацию метрик в оперативной памяти;
  5. Полную реализацию контракта ITransportChannel (Fail-closed).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / CP-55 / Rassvet_AI_Fabric#20.
"""

from __future__ import annotations

__version__ = "1.0.0"

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

logger = logging.getLogger("raif.failover_router")


class FailoverRouter(ITransportChannel):
    """Каскадный отказоустойчивый роутер моделей ИИ с отслеживанием лимитов и автоматическим восстановлением."""

    def __init__(
        self,
        primary_channel: ITransportChannel,
        haiku_channel: ITransportChannel,
        sonnet_channel: Optional[ITransportChannel] = None,
        retry_budget: int = 2,
    ) -> None:
        self.primary_channel = primary_channel
        self.haiku_channel = haiku_channel
        self.sonnet_channel = sonnet_channel
        self.retry_budget = max(1, retry_budget)

        self._fallback_active: bool = False
        self._current_fallback_tier: str = "none"  # "none", "haiku", "sonnet"
        self._fallback_start_ts: float = 0.0
        self._fallback_duration_seconds: float = 0.0
        self._model_switches_total: int = 0
        self._primary_consecutive_failures: int = 0
        self._inbox: queue.Queue[TransportMessageEnvelope] = queue.Queue()

    @property
    def status(self) -> TransportStatus:
        """Статус роутера: DEGRADED при работе в fallback, CONNECTED при штатной работе."""
        if self._fallback_active:
            return TransportStatus.DEGRADED
        return self.primary_channel.status

    @property
    def fallback_active(self) -> bool:
        """Флаг активности аварийного режима переключения на Claude."""
        return self._fallback_active

    @property
    def current_tier(self) -> str:
        """Текущий активный уровень маршрутизации: primary, haiku или sonnet."""
        if not self._fallback_active:
            return "primary"
        return self._current_fallback_tier

    @property
    def model_switches_total(self) -> int:
        """Общее количество зарегистрированных переключений моделей."""
        return self._model_switches_total

    def connect(self) -> bool:
        """Инициализация и подключение всех сконфигурированных каналов."""
        p_ok = self.primary_channel.connect()
        h_ok = self.haiku_channel.connect()
        s_ok = self.sonnet_channel.connect() if self.sonnet_channel else True
        return p_ok and h_ok and s_ok

    def disconnect(self) -> None:
        """Отключение всех каналов роутера."""
        self.primary_channel.disconnect()
        self.haiku_channel.disconnect()
        if self.sonnet_channel:
            self.sonnet_channel.disconnect()

    def is_connected(self) -> bool:
        """Проверка активности хотя бы одного рабочего канала."""
        if not self._fallback_active:
            return self.primary_channel.is_connected()
        if self._current_fallback_tier == "haiku":
            return self.haiku_channel.is_connected()
        if self._current_fallback_tier == "sonnet" and self.sonnet_channel:
            return self.sonnet_channel.is_connected()
        return False

    def probe_primary(self, timeout: float = 3.0) -> bool:
        """Проверка доступности первичного канала (Gemini)."""
        if hasattr(self.primary_channel, "probe"):
            try:
                return bool(self.primary_channel.probe(timeout=timeout))
            except Exception:
                return False
        return self.primary_channel.is_connected()

    def check_and_restore_primary(self) -> bool:
        """Проверка восстановления основной модели и автоматический возврат на неё."""
        if not self._fallback_active:
            return True

        if self.probe_primary():
            duration = time.time() - self._fallback_start_ts
            self._fallback_duration_seconds += max(0.0, duration)
            self._fallback_active = False
            self._current_fallback_tier = "none"
            self._primary_consecutive_failures = 0
            self._model_switches_total += 1
            logger.info("Primary Gemini channel recovered. Restored primary route.")
            return True
        return False

    def send(self, envelope: TransportMessageEnvelope) -> bool:
        """Отправка сообщения с обработкой отказов и автоматическим переключением."""
        if not envelope.verify_signature():
            raise TransportError("SIGNATURE_MISMATCH", "Envelope signature verification failed")

        # 1. Если работаем в штатном режиме
        if not self._fallback_active:
            try:
                success = self.primary_channel.send(envelope)
                if success:
                    self._primary_consecutive_failures = 0
                    self._drain_channel_response(self.primary_channel)
                    return True
            except TransportError as err:
                self._primary_consecutive_failures += 1
                logger.warning("Primary channel error (%s): %s", err.code, err)
                if self._primary_consecutive_failures < self.retry_budget and err.code != "RATE_LIMITED":
                    raise

            # Активируем fallback
            self._activate_fallback("haiku")

        # 2. Попытка отправки через Fallback Tier 1: Claude Haiku
        if self._fallback_active and self._current_fallback_tier == "haiku":
            try:
                success = self.haiku_channel.send(envelope)
                if success:
                    self._drain_channel_response(self.haiku_channel)
                    return True
            except TransportError as err:
                logger.warning("Haiku fallback channel error (%s): %s", err.code, err)
                if self.sonnet_channel is not None:
                    self._activate_fallback("sonnet")
                else:
                    raise TransportError("FAILOVER_EXHAUSTED", f"Haiku failed and no Sonnet tier configured: {err}")

        # 3. Попытка отправки через Fallback Tier 2: Claude Sonnet
        if self._fallback_active and self._current_fallback_tier == "sonnet" and self.sonnet_channel:
            try:
                success = self.sonnet_channel.send(envelope)
                if success:
                    self._drain_channel_response(self.sonnet_channel)
                    return True
            except TransportError as err:
                logger.error("Sonnet fallback channel error (%s): %s", err.code, err)
                raise TransportError("FAILOVER_EXHAUSTED", f"All fallback tiers exhausted: {err}")

        raise TransportError("FAILOVER_EXHAUSTED", "All primary and fallback model channels failed")

    def _activate_fallback(self, tier: str) -> None:
        """Активация соответствующего уровня резервирования."""
        self._fallback_active = True
        self._current_fallback_tier = tier
        self._fallback_start_ts = time.time()
        self._model_switches_total += 1
        logger.info("Activated Claude failover tier: %s", tier)

    def _drain_channel_response(self, channel: ITransportChannel, max_items: int = 10) -> None:
        """Считывание ответов из подлежащего канала во внутреннюю очередь (с ограничением max_items)."""
        for _ in range(max_items):
            try:
                resp = channel.receive(timeout=0.01)
                if resp is None:
                    break
                self._inbox.put(resp)
            except Exception:
                break

    def receive(self, timeout: float = 1.0) -> Optional[TransportMessageEnvelope]:
        """Получение ответа из объединённой очереди."""
        # Сначала проверяем внутренний буфер
        try:
            return self._inbox.get(block=True, timeout=timeout)
        except queue.Empty:
            pass

        # Если пусто, опрашиваем активный канал
        active_channel = self.primary_channel if not self._fallback_active else (
            self.haiku_channel if self._current_fallback_tier == "haiku" else self.sonnet_channel
        )
        if active_channel:
            return active_channel.receive(timeout=timeout)
        return None

    def get_metrics(self) -> Dict[str, Any]:
        """Получение среза метрик Zero SSD Wear из оперативной памяти."""
        current_duration = self._fallback_duration_seconds
        if self._fallback_active and self._fallback_start_ts > 0:
            current_duration += (time.time() - self._fallback_start_ts)

        return {
            "model_switches_total": self._model_switches_total,
            "fallback_active": self._fallback_active,
            "current_tier": self.current_tier,
            "fallback_duration_seconds": round(current_duration, 3),
            "primary_failures": self._primary_consecutive_failures,
            "primary_status": self.primary_channel.status.value,
            "haiku_status": self.haiku_channel.status.value,
            "sonnet_status": self.sonnet_channel.status.value if self.sonnet_channel else "NONE",
        }
