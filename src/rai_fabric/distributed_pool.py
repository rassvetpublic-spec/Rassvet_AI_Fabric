# -*- coding: utf-8 -*-
"""
rai_fabric.distributed_pool - Распределённый пул воркеров и RPC-маршрутизатор инференса (Stage R0.6).
Обеспечивает:
  1. Регистрацию локальных и удалённых воркеров флота (worker registration & health tracking);
  2. Балансировку нагрузки (least-loaded / round-robin dispatch);
  3. Маршрутизацию запросов инференса к LocalGpuTransport (порт 11434 / RTX 5070 Ti);
  4. Криптографическую верификацию пакетов TransportMessageEnvelope (fail-closed);
  5. Сбор метрик производительности (latency, throughput, worker availability).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R0.6 / Rassvet_AI_Fabric.
"""

from __future__ import annotations

__version__ = "1.0.0"

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from transport.ipc_channel import (
    TransportError,
    TransportMessageEnvelope,
    TransportStatus,
)
from .local_gpu_transport import LocalGpuTransport

logger = logging.getLogger("raif.distributed_pool")


class DistributedWorkerPool:
    """Управляющий координатор распределённого пула воркеров инференса и задач."""

    def __init__(
        self,
        gpu_transport: Optional[LocalGpuTransport] = None,
        max_queue_depth: int = 1000,
    ) -> None:
        self.gpu_transport = gpu_transport or LocalGpuTransport()
        self.max_queue_depth = max_queue_depth

        self._workers: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stats = {
            "dispatched_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "total_tokens": 0,
        }

    @property
    def registered_workers_count(self) -> int:
        with self._lock:
            return len(self._workers)

    def register_worker(
        self,
        worker_id: str,
        capabilities: Optional[List[str]] = None,
        endpoint: Optional[str] = None,
    ) -> bool:
        """Регистрация воркера в пуле."""
        with self._lock:
            self._workers[worker_id] = {
                "worker_id": worker_id,
                "capabilities": capabilities or ["inference", "code-eval"],
                "endpoint": endpoint or "local",
                "active_tasks": 0,
                "completed_tasks": 0,
                "last_seen": time.time(),
                "status": "ONLINE",
            }
            logger.info("Worker registered: %s (capabilities: %s)", worker_id, capabilities)
            return True

    def unregister_worker(self, worker_id: str) -> bool:
        """Исключение воркера из пула."""
        with self._lock:
            if worker_id in self._workers:
                del self._workers[worker_id]
                logger.info("Worker unregistered: %s", worker_id)
                return True
            return False

    def select_best_worker(self, required_capability: str = "inference") -> Optional[str]:
        """Выбор наименее загруженного воркера с требуемыми возможностями."""
        with self._lock:
            candidates = [
                w for w in self._workers.values()
                if w["status"] == "ONLINE" and required_capability in w["capabilities"]
            ]
            if not candidates:
                return None
            # Least-loaded selection
            candidates.sort(key=lambda x: (x["active_tasks"], x["completed_tasks"]))
            return candidates[0]["worker_id"]

    def dispatch_inference_task(
        self,
        prompt: str,
        task_id: Optional[str] = None,
        priority: int = 1,
    ) -> Dict[str, Any]:
        """Маршрутизация задачи инференса в распределённый пул."""
        worker_id = self.select_best_worker(required_capability="inference")
        if not worker_id:
            raise TransportError("NO_WORKERS_AVAILABLE", "No available worker with required capabilities")

        with self._lock:
            self._workers[worker_id]["active_tasks"] += 1
            self._stats["dispatched_tasks"] += 1

        env = TransportMessageEnvelope.create(
            payload_type="command",
            payload={"prompt": prompt, "task_id": task_id, "priority": priority},
            source=f"pool:{worker_id}",
        )

        # Верификация подписи пакета перед отправкой
        if not env.verify_signature():
            with self._lock:
                self._workers[worker_id]["active_tasks"] -= 1
                self._stats["failed_tasks"] += 1
            raise TransportError("SIGNATURE_MISMATCH", "Envelope cryptographic verification failed")

        t0 = time.time()
        try:
            if not self.gpu_transport.is_connected():
                self.gpu_transport.connect()

            self.gpu_transport.send(env)
            reply_env = self.gpu_transport.receive(timeout=15.0)

            duration_ms = round((time.time() - t0) * 1000.0, 2)

            if not reply_env or "reply" not in reply_env.payload:
                raise TransportError("INFERENCE_TIMEOUT", "Did not receive valid inference reply")

            reply_data = reply_env.payload["reply"]
            eval_count = reply_data.get("eval_count", 0)

            with self._lock:
                self._workers[worker_id]["active_tasks"] -= 1
                self._workers[worker_id]["completed_tasks"] += 1
                self._workers[worker_id]["last_seen"] = time.time()
                self._stats["completed_tasks"] += 1
                self._stats["total_tokens"] += eval_count

            return {
                "task_id": task_id or env.message_id,
                "assigned_worker": worker_id,
                "status": "COMPLETED",
                "duration_ms": duration_ms,
                "eval_count": eval_count,
                "response_text": reply_data.get("text", ""),
                "gpu_accelerated": reply_data.get("gpu_accelerated", False),
            }

        except Exception as exc:
            with self._lock:
                self._workers[worker_id]["active_tasks"] -= 1
                self._stats["failed_tasks"] += 1
            if isinstance(exc, TransportError):
                raise
            raise TransportError("DISPATCH_EXECUTION_ERROR", str(exc)) from exc

    def get_pool_status(self) -> Dict[str, Any]:
        """Получение агрегированного состояния пула."""
        with self._lock:
            return {
                "registered_workers": len(self._workers),
                "workers": list(self._workers.values()),
                "stats": dict(self._stats),
                "gpu_status": str(self.gpu_transport.status),
            }
