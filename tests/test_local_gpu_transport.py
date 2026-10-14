# -*- coding: utf-8 -*-
"""
tests.test_local_gpu_transport - Тесты адаптера локального GPU-инференса (Stage R0.3).
Покрывает:
  1. Определение аппаратного GPU (RTX 5070 Ti);
  2. Генерацию через синтетический mock-клиент (offline-safe);
  3. Проверку подписи конверта (SIGNATURE_MISMATCH);
  4. Защиту fail-closed при недоступности локального сервера Ollama.

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R0.3.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from rai_fabric.local_gpu_transport import (
    LocalGpuTransport,
    detect_local_gpu,
)
from transport.ipc_channel import (
    TransportError,
    TransportMessageEnvelope,
    TransportStatus,
)


class TestLocalGpuTransport(unittest.TestCase):
    """Тесты локального GPU-транспорта."""

    def test_detect_local_gpu_structure(self):
        info = detect_local_gpu()
        self.assertIsInstance(info, dict)
        self.assertIn("available", info)
        self.assertIn("name", info)
        self.assertIn("vram_mb", info)
        # Если запущено на машине с RTX 5070 Ti:
        if info["available"]:
            self.assertIn("RTX 5070", info["name"])
            self.assertGreater(info["vram_mb"], 10000)

    def test_mock_client_generation(self):
        mock = MagicMock()
        mock.generate.return_value = {
            "text": "def calculate_sum(a, b): return a + b",
            "eval_count": 15,
            "total_duration_ms": 12.5,
            "gpu_accelerated": True,
        }
        mock.probe.return_value = True

        transport = LocalGpuTransport(mock_client=mock)
        self.assertTrue(transport.connect())
        self.assertTrue(transport.is_connected())

        env = TransportMessageEnvelope.create(
            payload_type="command",
            payload={"prompt": "Write a python sum function"},
        )
        self.assertTrue(transport.send(env))
        self.assertEqual(transport.sent_count, 1)

        resp = transport.receive(timeout=0.1)
        self.assertIsNotNone(resp)
        assert resp is not None
        self.assertEqual(resp.payload_type, "response")
        self.assertIn("calculate_sum", resp.payload["reply"]["text"])
        self.assertTrue(resp.verify_signature())

    def test_tampered_envelope_rejected(self):
        mock = MagicMock()
        transport = LocalGpuTransport(mock_client=mock)
        transport.connect()

        env = TransportMessageEnvelope.create(
            payload_type="command",
            payload={"prompt": "Legit"},
        )
        env.payload["prompt"] = "Tampered"

        with self.assertRaises(TransportError) as ctx:
            transport.send(env)
        self.assertEqual(ctx.exception.code, "SIGNATURE_MISMATCH")

    def test_offline_when_server_absent(self):
        # Подключение к заведомо закрытому локальному порту
        transport = LocalGpuTransport(endpoint_url="http://127.0.0.1:59999", mock_client=None)
        res = transport.connect()
        self.assertFalse(res)
        self.assertEqual(transport.status, TransportStatus.DEGRADED)


if __name__ == "__main__":
    unittest.main()
