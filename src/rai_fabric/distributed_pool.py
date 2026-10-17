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


class WeightedLoadBalancer:
    """Взвешенный балансировщик нагрузки с алгоритмом Work-Stealing (Stage R33 / R7)."""

    @staticmethod
    def score_worker(
        vram_free_mb: float,
        compute_power: float,
        active_tasks: int,
        task_tokens: int = 1000,
    ) -> float:
        """
        Формула скоринга воркера:
        Score = (VRAM_free * ComputePower) / ((1 + active_tasks) * (1 + task_tokens / 4096))
        """
        vram = max(100.0, float(vram_free_mb))
        power = max(0.1, float(compute_power))
        active = max(0, int(active_tasks))
        tokens_penalty = 1.0 + (max(1, int(task_tokens)) / 4096.0)
        return (vram * power) / ((1.0 + active) * tokens_penalty)


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
        vram_free_mb: float = 8000.0,
        compute_power: float = 1.0,
    ) -> bool:
        """Регистрация воркера в пуле с аппаратным профилем."""
        with self._lock:
            self._workers[worker_id] = {
                "worker_id": worker_id,
                "capabilities": capabilities or ["inference", "code-eval"],
                "endpoint": endpoint or "local",
                "active_tasks": 0,
                "completed_tasks": 0,
                "last_seen": time.time(),
                "status": "ONLINE",
                "vram_free_mb": float(vram_free_mb),
                "compute_power": float(compute_power),
                "pending_queue": [],
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

    def select_best_worker(
        self,
        required_capability: str = "inference",
        task_tokens: int = 1000,
    ) -> Optional[str]:
        """Выбор лучшего воркера с использованием взвешенного скоринга (R7)."""
        with self._lock:
            candidates = [
                w for w in self._workers.values()
                if w["status"] == "ONLINE" and required_capability in w["capabilities"]
            ]
            if not candidates:
                return None
            candidates.sort(
                key=lambda w: WeightedLoadBalancer.score_worker(
                    vram_free_mb=w.get("vram_free_mb", 8000.0),
                    compute_power=w.get("compute_power", 1.0),
                    active_tasks=w.get("active_tasks", 0) + len(w.get("pending_queue", [])),
                    task_tokens=task_tokens,
                ),
                reverse=True,
            )
            return candidates[0]["worker_id"]

    def enqueue_worker_task(self, worker_id: str, task: Dict[str, Any]) -> bool:
        """Помещение задачи в очередь конкретного воркера."""
        with self._lock:
            if worker_id not in self._workers:
                return False
            self._workers[worker_id]["pending_queue"].append(task)
            return True

    def steal_work(self, idle_worker_id: str) -> Optional[Dict[str, Any]]:
        """Проактивный перехват задачи из хвоста наиболее загруженного воркера (Work-Stealing / R7)."""
        with self._lock:
            if idle_worker_id not in self._workers:
                return None

            busiest_worker = None
            max_queue_len = 0
            for w_id, w in self._workers.items():
                if w_id != idle_worker_id and w["status"] == "ONLINE":
                    q_len = len(w.get("pending_queue", []))
                    if q_len > max_queue_len:
                        max_queue_len = q_len
                        busiest_worker = w

            if busiest_worker and max_queue_len > 0:
                stolen_task = busiest_worker["pending_queue"].pop()
                logger.info(
                    "WorkStealing: worker '%s' stole task '%s' from '%s'",
                    idle_worker_id,
                    stolen_task.get("task_id"),
                    busiest_worker["worker_id"],
                )
                return stolen_task

            return None

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
