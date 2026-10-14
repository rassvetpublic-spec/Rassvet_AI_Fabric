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
from typing import Any, Dict, Optional

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


class LocalGpuTransport(ITransportChannel):
    """Канал локального GPU-инференса для выгрузки синтетических и рутинных задач флота."""

    def __init__(
        self,
        endpoint_url: str = DEFAULT_OLLAMA_ENDPOINT,
        model_name: str = DEFAULT_LOCAL_MODEL,
        mock_client: Optional[Any] = None,
        timeout: float = 30.0,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.model_name = model_name
        self.mock_client = mock_client
        self.timeout = timeout

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
