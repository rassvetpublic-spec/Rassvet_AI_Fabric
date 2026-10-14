# -*- coding: utf-8 -*-
"""
tests/test_stress_distributed_pool.py - 100% offline-safe тесты стресс-бенчмарка DistributedWorkerPool.
"""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from scripts.stress_distributed_pool import main, run_stress_test
from transport.ipc_channel import TransportMessageEnvelope, TransportStatus


class TestStressDistributedPool:
    def test_run_stress_test_mocked(self) -> None:
        mock_transport = MagicMock()
        mock_transport.is_connected.return_value = True
        mock_transport.status = TransportStatus.CONNECTED

        def mock_receive(timeout: float = 15.0):
            return TransportMessageEnvelope.create(
                payload_type="reply",
                payload={"reply": {"text": "dummy code", "eval_count": 100, "gpu_accelerated": True}},
            )

        mock_transport.receive.side_effect = mock_receive

        with patch("scripts.stress_distributed_pool.LocalGpuTransport", return_value=mock_transport):
            with patch("scripts.stress_distributed_pool.query_gpu_telemetry", return_value={"available": True, "temperature_c": 45}):
                report = run_stress_test(concurrency=2, total_tasks=4, worker_count=2)

        assert report["status"] == "PASS"
        assert report["total_tasks"] == 4
        assert report["completed_tasks"] == 4
        assert report["failed_tasks"] == 0
        assert report["total_tokens"] == 400
        assert "worker-gpu-01" in report["pool_distribution"]
        assert "worker-gpu-02" in report["pool_distribution"]

    def test_main_cli_json(self) -> None:
        mock_report = {
            "status": "PASS",
            "total_tasks": 2,
            "completed_tasks": 2,
            "failed_tasks": 0,
            "total_tokens": 200,
            "total_duration_ms": 100.0,
            "avg_latency_ms": 50.0,
            "tokens_per_sec": 2000.0,
            "gpu_telemetry": {"available": True},
            "pool_distribution": {},
        }
        with patch("scripts.stress_distributed_pool.run_stress_test", return_value=mock_report):
            output = io.StringIO()
            with patch("sys.stdout", output):
                code = main(["--tasks", "2", "--json"])
            assert code == 0
            parsed = json.loads(output.getvalue())
            assert parsed["status"] == "PASS"
            assert parsed["total_tasks"] == 2
