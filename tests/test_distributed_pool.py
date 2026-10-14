# -*- coding: utf-8 -*-
"""
tests.test_distributed_pool - Тесты распределённого пула воркеров DistributedWorkerPool (Stage R0.6).
Покрывает:
  1. Регистрацию и разрегистрацию воркеров;
  2. Балансировку нагрузки (least-loaded selection);
  3. Маршрутизацию задач инференса через LocalGpuTransport;
  4. Защиту от отсутствия доступных воркеров (NO_WORKERS_AVAILABLE);
  5. Сбор и корректность метрик пула.

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R0.6.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from rai_fabric.distributed_pool import DistributedWorkerPool
from rai_fabric.local_gpu_transport import LocalGpuTransport
from transport.ipc_channel import TransportError


class TestDistributedWorkerPool(unittest.TestCase):
    """Тесты распределённого пула воркеров."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client.generate.return_value = {
            "text": "def distributed_eval(): return True",
            "eval_count": 32,
            "total_duration_ms": 15.0,
            "gpu_accelerated": True,
        }
        self.mock_client.probe.return_value = True

        self.gpu_transport = LocalGpuTransport(mock_client=self.mock_client)
        self.pool = DistributedWorkerPool(gpu_transport=self.gpu_transport)

    def test_register_and_unregister_worker(self):
        self.assertEqual(self.pool.registered_workers_count, 0)
        self.assertTrue(self.pool.register_worker("worker-gpu-01", ["inference", "code-eval"]))
        self.assertEqual(self.pool.registered_workers_count, 1)

        self.assertTrue(self.pool.unregister_worker("worker-gpu-01"))
        self.assertEqual(self.pool.registered_workers_count, 0)
        self.assertFalse(self.pool.unregister_worker("nonexistent"))

    def test_select_best_worker_least_loaded(self):
        self.pool.register_worker("worker-a", ["inference"])
        self.pool.register_worker("worker-b", ["inference"])

        best = self.pool.select_best_worker("inference")
        self.assertIn(best, ["worker-a", "worker-b"])

        # Увеличиваем нагрузку на worker-a
        self.pool._workers["worker-a"]["active_tasks"] = 3
        best2 = self.pool.select_best_worker("inference")
        self.assertEqual(best2, "worker-b")

    def test_dispatch_inference_task_success(self):
        self.pool.register_worker("worker-node-1", ["inference"])
        res = self.pool.dispatch_inference_task(
            prompt="Generate code test",
            task_id="task-dist-01",
        )

        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["assigned_worker"], "worker-node-1")
        self.assertEqual(res["eval_count"], 32)
        self.assertIn("distributed_eval", res["response_text"])

        status = self.pool.get_pool_status()
        self.assertEqual(status["stats"]["completed_tasks"], 1)
        self.assertEqual(status["stats"]["total_tokens"], 32)

    def test_dispatch_when_no_workers_fails_closed(self):
        with self.assertRaises(TransportError) as ctx:
            self.pool.dispatch_inference_task("Fail prompt")
        self.assertEqual(ctx.exception.code, "NO_WORKERS_AVAILABLE")


if __name__ == "__main__":
    unittest.main()
