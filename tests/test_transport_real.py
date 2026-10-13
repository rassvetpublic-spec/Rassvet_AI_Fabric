# -*- coding: utf-8 -*-
"""
tests.test_transport_real - Комплексные тесты реального боевого транспорта RAiF (Stage R25).
Покрывает:
  1. Контракты TransportMessageEnvelope (SHA-256 подпись, фальсификация, сериализация);
  2. Windows Named Pipe сервер и клиент (эхо, рассылка, автопереподключение);
  3. Резервный HTTP сервер и клиент (порт fallback, проверка здоровья, long-polling);
  4. Мост метрик FleetMetricsBridge (Zero SSD Wear RAM-буфер, потоковая передача);
  5. Интеграционный адаптер RealTransportAdapter и мост супервизора (Supervisor Bridge).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.2) / RAiF 10.7 Stage R25 / Rassvet_AI_Fabric#15.
"""

from __future__ import annotations

import json
import os
import time
import unittest
from unittest.mock import MagicMock, patch

from transport.ipc_channel import (
    ITransportChannel,
    TransportError,
    TransportMessageEnvelope,
    TransportStatus,
)
from transport.real_transport import (
    DEFAULT_FALLBACK_PORT,
    DEFAULT_METRICS_PIPE,
    DEFAULT_RAIF_PIPE,
    FleetMetricsBridge,
    HttpFallbackClient,
    HttpFallbackServer,
    NamedPipeClient,
    NamedPipeServer,
    RealTransportAdapter,
)


class TestTransportMessageEnvelope(unittest.TestCase):
    """Тесты канонического конверта сообщений и криптографических инвариантов."""

    def test_create_and_signature_validity(self):
        envelope = TransportMessageEnvelope.create(
            payload_type="command",
            payload={"action": "RUN_UNIT_TESTS", "timeout": 30},
            channel="raif_transport",
            source="test_runner",
        )
        self.assertIsNotNone(envelope.signature)
        self.assertTrue(envelope.verify_signature())
        self.assertEqual(envelope.payload_type, "command")
        self.assertEqual(envelope.payload["action"], "RUN_UNIT_TESTS")

    def test_tampering_detection(self):
        envelope = TransportMessageEnvelope.create(
            payload_type="command",
            payload={"action": "SAFE_READ"},
        )
        self.assertTrue(envelope.verify_signature())

        # Имитация злонамеренной подмены полезной нагрузки
        envelope.payload["action"] = "UNAUTHORIZED_WRITE"
        self.assertFalse(envelope.verify_signature())

        # Попытка десериализации модифицированного словаря должна вызывать отказ (fail-closed)
        data = envelope.to_dict()
        with self.assertRaises(TransportError) as ctx:
            TransportMessageEnvelope.from_dict(data, verify=True)
        self.assertEqual(ctx.exception.code, "SIGNATURE_MISMATCH")

    def test_json_and_bytes_roundtrip(self):
        orig = TransportMessageEnvelope.create(
            payload_type="json_rpc",
            payload={"method": "ping", "id": 42},
            headers={"trace_id": "tr_107_r25"},
        )
        raw_bytes = orig.to_bytes()
        restored = TransportMessageEnvelope.from_json(raw_bytes)
        self.assertEqual(orig.message_id, restored.message_id)
        self.assertEqual(orig.timestamp, restored.timestamp)
        self.assertEqual(orig.signature, restored.signature)
        self.assertEqual(restored.headers.get("trace_id"), "tr_107_r25")
        self.assertTrue(restored.verify_signature())

    def test_missing_required_fields_fails_closed(self):
        invalid_data = {"message_id": "123", "timestamp": "now"}
        with self.assertRaises(TransportError) as ctx:
            TransportMessageEnvelope.from_dict(invalid_data)
        self.assertEqual(ctx.exception.code, "MISSING_ENVELOPE_FIELD")


class TestNamedPipeTransport(unittest.TestCase):
    """Интеграционные тесты Named Pipe сервера и клиента с авто-переподключением."""

    def setUp(self):
        # Используем выделенный изолированный порт для надежных кроссплатформенных юнит-тестов
        self.test_port = 18881
        self.test_pipe = r"\\.\pipe\raif_test_transport_18881"
        self.server = NamedPipeServer(
            pipe_name=self.test_pipe,
            inet_fallback_port=self.test_port,
        )
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def test_client_connect_send_receive(self):
        client = NamedPipeClient(
            pipe_name=self.test_pipe,
            inet_fallback_port=self.test_port,
            auto_reconnect=False,
        )
        try:
            connected = client.connect()
            self.assertTrue(connected, "Клиент должен успешно подключиться к серверу")
            self.assertEqual(client.status, TransportStatus.CONNECTED)

            envelope = TransportMessageEnvelope.create(
                payload_type="heartbeat",
                payload={"status": "ALIVE", "worker_id": "worker_01"},
            )
            sent = client.send(envelope)
            self.assertTrue(sent)

            # Сервер получает сообщение
            received = self.server.receive(timeout=3.0)
            self.assertIsNotNone(received)
            assert received is not None
            self.assertEqual(received.message_id, envelope.message_id)
            self.assertEqual(received.payload["worker_id"], "worker_01")
            self.assertTrue(received.verify_signature())
        finally:
            client.disconnect()
            self.assertEqual(client.status, TransportStatus.CLOSED)

    def test_server_broadcast_to_client(self):
        client = NamedPipeClient(
            pipe_name=self.test_pipe,
            inet_fallback_port=self.test_port,
            auto_reconnect=False,
        )
        try:
            connected = client.connect()
            self.assertTrue(connected)
            time.sleep(0.1)  # Дать серверу принять сокет

            envelope = TransportMessageEnvelope.create(
                payload_type="broadcast",
                payload={"announcement": "FLEET_UPDATE_READY"},
            )
            count = self.server.broadcast(envelope)
            self.assertGreaterEqual(count, 1)

            # Клиент получает рассылку
            msg = client.receive(timeout=3.0)
            self.assertIsNotNone(msg)
            assert msg is not None
            self.assertEqual(msg.payload["announcement"], "FLEET_UPDATE_READY")
        finally:
            client.disconnect()


class TestHttpFallbackGateway(unittest.TestCase):
    """Тесты резервного HTTP шлюза 127.0.0.1:18892 (Fallback Layer)."""

    def setUp(self):
        self.fallback_port = 18882
        self.server = HttpFallbackServer(host="127.0.0.1", port=self.fallback_port)
        self.server.start()
        time.sleep(0.05)

    def tearDown(self):
        self.server.stop()

    def test_health_check_and_status(self):
        client = HttpFallbackClient(host="127.0.0.1", port=self.fallback_port)
        connected = client.connect()
        self.assertTrue(connected)
        self.assertTrue(client.is_connected())

    def test_http_send_and_poll_message(self):
        client = HttpFallbackClient(host="127.0.0.1", port=self.fallback_port)
        self.assertTrue(client.connect())

        envelope = TransportMessageEnvelope.create(
            payload_type="task_intent",
            payload={"task_id": "TASK_10_7_001", "complexity": "B-X"},
        )
        success = client.send(envelope)
        self.assertTrue(success)

        # Опрос очереди сообщений через клиент
        msg = client.receive(timeout=2.0)
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertEqual(msg.message_id, envelope.message_id)
        self.assertEqual(msg.payload["task_id"], "TASK_10_7_001")


class TestFleetMetricsBridge(unittest.TestCase):
    """Тесты стриминга метрик в сокет fleet_metrics и RAM-буфера (Zero SSD Wear)."""

    def test_ram_buffering_when_offline(self):
        bridge = FleetMetricsBridge(
            pipe_name=r"\\.\pipe\nonexistent_test_pipe_99999",
            inet_port=18889,
            max_ram_buffer=100,
        )
        try:
            # Сокет оффлайн — событие должно поместиться в RAM-буфер без падения и без дискового I/O
            success = bridge.emit_event("test_metric", {"cpu_percent": 14.2})
            self.assertFalse(success, "При отсутствии сервера должен возвращаться False (fallback в ОЗУ)")
            self.assertEqual(bridge.buffered_count, 1)

            # Heartbeat тоже буферизуется
            bridge.emit_heartbeat("worker_node", "ACTIVE")
            self.assertEqual(bridge.buffered_count, 2)
        finally:
            bridge.close()


class TestRealTransportAdapter(unittest.TestCase):
    """Тесты координатора RealTransportAdapter и интеграции с UnifiedSupervisor."""

    def test_adapter_initialization_and_supervisor_bridge(self):
        # Настройка адаптера на изолированные тестовые эндпоинты
        adapter = RealTransportAdapter(
            pipe_name=r"\\.\pipe\test_raif_adapter_pipe",
            fallback_port=18883,
            metrics_pipe=r"\\.\pipe\test_fleet_metrics_adapter",
            inet_fallback_port=18884,
        )

        try:
            # Запуск в изолированном тестовом режиме без фонового сердцебиения
            adapter.start(start_heartbeat=False)
            self.assertIn(adapter.active_channel_name, ("NAMED_PIPE", "HTTP_FALLBACK", "DEGRADED_OFFLINE"))

            # Проверка Supervisor Bridge
            status_data = {
                "supervisor_pid": os.getpid(),
                "active_accounts": 3,
                "has_valid_patch": True,
            }
            res = adapter.register_supervisor_status(status_data)
            self.assertTrue(res)

            # Проверка маршрутизации запроса к модели
            routing = adapter.route_model_request(
                target_account="acc_alexa_01",
                prompt="Проверить статус транспорта",
                session_id="sess_r25_001",
            )
            self.assertTrue(routing["routed"])
            self.assertEqual(routing["target_account"], "acc_alexa_01")
            self.assertIn("envelope_id", routing)
        finally:
            adapter.stop()


if __name__ == "__main__":
    unittest.main()
