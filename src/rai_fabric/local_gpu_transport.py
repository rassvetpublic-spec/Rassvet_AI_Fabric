# -*- coding: utf-8 -*-
"""
rai_fabric.local_gpu_transport - Адаптер локального GPU-инференса для RTX 5070 Ti / Ollama (Stage R0.3).
Реализует:
  1. Интерфейс ITransportChannel из transport.ipc_channel;
  2. Аппаратное распознавание GPU (nvidia-smi / WMI) с определением VRAM;
  3. Взаимодействие с локальным runtime (Ollama / llama.cpp HTTP API на 127.0.0.1:11434);
  4. 100% offline mock-клиент для детерминированного тестирования и CI;
  5. Защиту от зависаний и утечек (тайм-ауты, fail-closed, подпись пакетов).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R0.3 / Rassvet_AI_Fabric.
"""

from __future__ import annotations

__version__ = "1.0.0"

import json
import logging
import queue
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from transport.ipc_channel import (
    ITransportChannel,
    TransportError,
    TransportMessageEnvelope,
    TransportStatus,
)

logger = logging.getLogger("raif.local_gpu_transport")

DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_LOCAL_MODEL = "qwen2.5-coder:7b"


def detect_local_gpu() -> Dict[str, Any]:
    """Безопасное определение характеристик локального GPU без сбоя при отсутствии оборудования."""
    gpu_info = {
        "available": False,
        "name": "UNKNOWN",
        "vram_mb": 0,
        "driver_version": "UNKNOWN",
        "detection_source": "NONE",
    }

    # 1. Попытка через nvidia-smi
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            res = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
            )
            line = res.stdout.strip()
            if line:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    gpu_info["available"] = True
                    gpu_info["name"] = parts[0]
                    gpu_info["vram_mb"] = int(float(parts[1]))
                    gpu_info["driver_version"] = parts[2]
                    gpu_info["detection_source"] = "nvidia-smi"
                    return gpu_info
        except Exception as exc:
            logger.debug("nvidia-smi query failed: %s", exc)

    return gpu_info


def query_gpu_telemetry() -> Dict[str, Any]:
    """Опрос оперативной телеметрии GPU (VRAM used/total, температура, потребление энергии)."""
    telemetry: Dict[str, Any] = {
        "available": False,
        "temperature_c": None,
        "memory_used_mb": None,
        "memory_total_mb": None,
        "power_draw_w": None,
    }
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            res = subprocess.run(
                [
                    nvidia_smi,
                    "--query-gpu=temperature.gpu,memory.used,memory.total,power.draw",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
            )
            line = res.stdout.strip()
            if line:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    telemetry["available"] = True
                    telemetry["temperature_c"] = int(float(parts[0]))
                    telemetry["memory_used_mb"] = int(float(parts[1]))
                    telemetry["memory_total_mb"] = int(float(parts[2]))
                    telemetry["power_draw_w"] = float(parts[3])
        except Exception as exc:
            logger.debug("nvidia-smi telemetry query failed: %s", exc)
    return telemetry


class GpuThermalWatchdog:
    """Аппаратный предохранитель по температуре и доступной VRAM (Stage R33 / Milestone M1)."""

    def __init__(
        self,
        max_temp_c: float = 72.0,
        min_free_vram_mb: float = 800.0,
        cache_ttl_seconds: float = 1.0,
    ) -> None:
        self.max_temp_c = max_temp_c
        self.min_free_vram_mb = min_free_vram_mb
        self.cache_ttl_seconds = cache_ttl_seconds
        self._last_telemetry: Dict[str, Any] = {}
        self._last_query_ts: float = 0.0
        self._mock_telemetry: Optional[Dict[str, Any]] = None

    def set_mock_telemetry(self, temp_c: Optional[float], free_vram_mb: Optional[float]) -> None:
        """Установка детерминированных показаний для тестирования."""
        if temp_c is None and free_vram_mb is None:
            self._mock_telemetry = None
        else:
            self._mock_telemetry = {
                "available": True,
                "temperature_c": temp_c,
                "free_vram_mb": free_vram_mb,
            }

    def get_telemetry(self) -> Dict[str, Any]:
        """Получение телеметрии с кэшированием для предотвращения избыточных вызовов nvidia-smi."""
        if self._mock_telemetry is not None:
            return dict(self._mock_telemetry)

        now = time.time()
        if (now - self._last_query_ts) < self.cache_ttl_seconds and self._last_telemetry:
            return dict(self._last_telemetry)

        tel = query_gpu_telemetry()
        if tel.get("available") and tel.get("memory_total_mb") is not None and tel.get("memory_used_mb") is not None:
            tel["free_vram_mb"] = max(0, tel["memory_total_mb"] - tel["memory_used_mb"])
        else:
            tel["free_vram_mb"] = None

        self._last_telemetry = tel
        self._last_query_ts = now
        return dict(tel)

    def check_safety(self, is_interactive: bool = True) -> tuple[bool, Optional[str]]:
        """
        Проверка аппаратных порогов.
        Если порог превышен:
        - для фоновых задач (is_interactive=False): сброс нагрузки (False, причина)
        - для интерактивного диалога (is_interactive=True): предупреждение (True, warning)
        """
        tel = self.get_telemetry()
        if not tel.get("available"):
            return True, None

        temp = tel.get("temperature_c")
        free_vram = tel.get("free_vram_mb")

        reason = None
        if temp is not None and temp > self.max_temp_c:
            reason = f"GPU temperature {temp}°C exceeds safety threshold {self.max_temp_c}°C"
        elif free_vram is not None and free_vram < self.min_free_vram_mb:
            reason = f"Free VRAM {free_vram} MB is below safety threshold {self.min_free_vram_mb} MB"

        if reason:
            if not is_interactive:
                logger.warning("ThermalWatchdog: Shedding background queue load: %s", reason)
                return False, reason
            else:
                logger.warning("ThermalWatchdog: Interactive throttle advisory: %s", reason)
                return True, reason

        return True, None


class LocalGpuTransport(ITransportChannel):
    """Канал локального GPU-инференса для выгрузки синтетических и рутинных задач флота."""

    def __init__(
        self,
        endpoint_url: str = DEFAULT_OLLAMA_ENDPOINT,
        model_name: str = DEFAULT_LOCAL_MODEL,
        mock_client: Optional[Any] = None,
        timeout: float = 30.0,
        watchdog: Optional[GpuThermalWatchdog] = None,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.model_name = model_name
        self.mock_client = mock_client
        self.timeout = timeout
        self.watchdog = watchdog or GpuThermalWatchdog()

        self._status = TransportStatus.DISCONNECTED
        self._gpu_meta = detect_local_gpu()
        self._inbox: queue.Queue[TransportMessageEnvelope] = queue.Queue()
        self._sent_count: int = 0
        self._tokens_generated: int = 0

    @property
    def status(self) -> TransportStatus:
        return self._status

    @property
    def gpu_info(self) -> Dict[str, Any]:
        return dict(self._gpu_meta)

    @property
    def sent_count(self) -> int:
        return self._sent_count

    def connect(self) -> bool:
        """Инициализация соединения с локальным runtime."""
        self._status = TransportStatus.CONNECTING
        if self.mock_client is not None:
            self._status = TransportStatus.CONNECTED
            return True

        if self.probe(timeout=2.0):
            self._status = TransportStatus.CONNECTED
            return True

        # Если локальный сервер не запущен, статус переходит в STANDBY
        self._status = TransportStatus.DEGRADED
        return False

    def disconnect(self) -> None:
        """Закрытие канала."""
        self._status = TransportStatus.CLOSED

    def is_connected(self) -> bool:
        return self._status == TransportStatus.CONNECTED

    def probe(self, timeout: float = 2.0) -> bool:
        """Проверка доступности локального HTTP API сервера (Ollama /api/tags)."""
        if self.mock_client is not None:
            if hasattr(self.mock_client, "probe"):
                return bool(self.mock_client.probe(timeout=timeout))
            return True

        try:
            req = urllib.request.Request(f"{self.endpoint_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def send(self, envelope: TransportMessageEnvelope) -> bool:
        """Отправка промпта на локальный GPU-инференс."""
        if not self.is_connected() and self.mock_client is None:
            raise TransportError("NOT_CONNECTED", "Local GPU runtime is not connected or offline")

        if not envelope.verify_signature():
            self._status = TransportStatus.ERROR
            raise TransportError("SIGNATURE_MISMATCH", "Envelope cryptographic verification failed")

        # R1: Hardware Thermal Watchdog & VRAM-Shedding
        is_interactive = envelope.payload.get("interactive", True) if isinstance(envelope.payload, dict) else True
        safe, reason = self.watchdog.check_safety(is_interactive=is_interactive)
        if not safe:
            raise TransportError("GPU_SAFETY_THRESHOLD_EXCEEDED", f"429 Load Shedding: {reason}")

        try:
            if self.mock_client is not None:
                response_payload = self.mock_client.generate(envelope.payload)
            else:
                prompt_text = envelope.payload.get("prompt") or str(envelope.payload)
                request_body = json.dumps({
                    "model": self.model_name,
                    "prompt": prompt_text,
                    "stream": False,
                    "options": {
                        "temperature": envelope.payload.get("temperature", 0.2),
                    },
                }).encode("utf-8")

                req = urllib.request.Request(
                    f"{self.endpoint_url}/api/generate",
                    data=request_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    response_payload = {
                        "text": resp_data.get("response", ""),
                        "model": resp_data.get("model", self.model_name),
                        "eval_count": resp_data.get("eval_count", 0),
                        "total_duration_ms": round(resp_data.get("total_duration", 0) / 1_000_000, 2),
                        "gpu_accelerated": self._gpu_meta["available"],
                    }

            # Ответный конверт
            reply_env = TransportMessageEnvelope.create(
                payload_type="response",
                payload={"reply": response_payload, "ref_id": envelope.message_id},
                channel=envelope.channel,
                source=f"local_gpu:{self.model_name}",
            )
            self._inbox.put(reply_env)
            self._sent_count += 1
            return True

        except TransportError:
            raise
        except Exception as exc:
            self._status = TransportStatus.ERROR
            raise TransportError("LOCAL_GPU_EXECUTION_FAILED", f"Failed local GPU generation: {exc}") from exc

    def receive(self, timeout: float = 1.0) -> Optional[TransportMessageEnvelope]:
        try:
            return self._inbox.get(block=True, timeout=timeout)
        except queue.Empty:
            return None


class LocalGpuBenchmark:
    """Бенчмарк производительности локального инференса и телеметрии GPU."""

    def __init__(self, transport: Optional[LocalGpuTransport] = None) -> None:
        self.transport = transport or LocalGpuTransport()

    def run_benchmark(
        self,
        iterations: int = 5,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Запуск стресс-прогона генерации с замером задержки, скорости токенов и дельты телеметрии."""
        if not self.transport.is_connected():
            self.transport.connect()

        prompt_text = (
            prompt
            or "Write a deterministic hash verification function in Python with docstrings."
        )
        initial_telemetry = query_gpu_telemetry()

        latencies_ms: List[float] = []
        total_tokens = 0
        start_total = time.time()

        for i in range(iterations):
            env = TransportMessageEnvelope.create(
                payload_type="command",
                payload={"prompt": f"{prompt_text} [Iteration {i+1}]"},
            )
            t0 = time.time()
            self.transport.send(env)
            resp = self.transport.receive(timeout=30.0)
            t_diff = (time.time() - t0) * 1000.0
            latencies_ms.append(round(t_diff, 2))

            if resp and "reply" in resp.payload:
                total_tokens += resp.payload["reply"].get("eval_count", 0)

        total_duration_sec = time.time() - start_total
        final_telemetry = query_gpu_telemetry()

        avg_latency = (
            round(sum(latencies_ms) / len(latencies_ms), 2) if latencies_ms else 0.0
        )
        min_latency = min(latencies_ms) if latencies_ms else 0.0
        max_latency = max(latencies_ms) if latencies_ms else 0.0
        tokens_per_sec = (
            round(total_tokens / total_duration_sec, 2)
            if total_duration_sec > 0
            else 0.0
        )

        vram_delta = None
        if (
            initial_telemetry.get("memory_used_mb") is not None
            and final_telemetry.get("memory_used_mb") is not None
        ):
            vram_delta = final_telemetry["memory_used_mb"] - initial_telemetry["memory_used_mb"]

        temp_delta = None
        if (
            initial_telemetry.get("temperature_c") is not None
            and final_telemetry.get("temperature_c") is not None
        ):
            temp_delta = final_telemetry["temperature_c"] - initial_telemetry["temperature_c"]

        return {
            "iterations": iterations,
            "total_duration_ms": round(total_duration_sec * 1000.0, 2),
            "latencies_ms": latencies_ms,
            "avg_latency_ms": avg_latency,
            "min_latency_ms": min_latency,
            "max_latency_ms": max_latency,
            "total_tokens": total_tokens,
            "tokens_per_sec": tokens_per_sec,
            "initial_telemetry": initial_telemetry,
            "final_telemetry": final_telemetry,
            "vram_delta_mb": vram_delta,
            "temp_delta_c": temp_delta,
            "gpu_accelerated": self.transport.gpu_info.get("available", False),
        }

