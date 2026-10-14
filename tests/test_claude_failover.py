# -*- coding: utf-8 -*-
"""
tests.test_claude_failover - Комплексные офлайн-тесты горячего переключения на Claude (CP-55).
Покрывает:
  1. Работу ClaudeVertexTransport с синтетическим mock-клиентом (100% offline-safe);
  2. Перехват ошибок квот 429 / 503 и выброс TransportError(RATE_LIMITED / SERVICE_UNAVAILABLE);
  3. Каскадную маршрутизацию в FailoverRouter:
     - Штатный путь (Gemini);
     - Failover Tier 1 (Claude Haiku) при 429 на primary;
     - Failover Tier 2 (Claude Sonnet) при сбое Haiku;
     - Автоматический возврат на primary (RETURN_TO_PRIMARY_ON_RECOVERY);
     - Исчерпание всех уровней (FAIL_CLOSED);
  4. Проверку криптографической целостности конвертов (SIGNATURE_MISMATCH);
  5. Учёт метрик Zero SSD Wear в оперативной памяти.

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / CP-55 / Rassvet_AI_Fabric#20.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from rai_fabric.claude_vertex_transport import ClaudeVertexTransport
from rai_fabric.failover_router import FailoverRouter
from transport.ipc_channel import (
    ITransportChannel,
    TransportError,
    TransportMessageEnvelope,
    TransportStatus,
)


class DummyMockChannel(ITransportChannel):
    """Синтетический управляемый канал для тестирования роутера."""

    def __init__(self, name: str, should_fail: bool = False, fail_code: str = "RATE_LIMITED"):
        self.name = name
        self.should_fail = should_fail
        self.fail_code = fail_code
        self._connected = True
        self.history = []
        self.pending_responses = []

    @property
    def status(self) -> TransportStatus:
        return TransportStatus.CONNECTED if self._connected else TransportStatus.DISCONNECTED

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def probe(self, timeout: float = 3.0) -> bool:
        return not self.should_fail

    def send(self, envelope: TransportMessageEnvelope) -> bool:
        if self.should_fail:
            raise TransportError(self.fail_code, f"Simulated failure on {self.name}")
        self.history.append(envelope)
        self.pending_responses.append(envelope)
        return True

    def receive(self, timeout: float = 1.0) -> TransportMessageEnvelope | None:
        if not self.pending_responses:
            return None
        last = self.pending_responses.pop(0)
        return TransportMessageEnvelope.create(
            payload_type="response",
            payload={"ack": self.name, "ref": last.message_id},
            channel=last.channel,
            source=self.name,
        )


class TestClaudeVertexTransport(unittest.TestCase):
    """Тесты адаптера ClaudeVertexTransport."""

    def test_mock_client_send_and_receive(self):
        mock_client = MagicMock()
        mock_client.send.return_value = {"text": "Hello from Claude Haiku", "tokens": 42}
        mock_client.probe.return_value = True

        transport = ClaudeVertexTransport(
            project_id="test-proj",
            region="us-east5",
            model_name="claude-3-5-haiku@20241022",
            mock_client=mock_client,
        )
        self.assertTrue(transport.connect())
        self.assertTrue(transport.is_connected())
        self.assertTrue(transport.probe())

        env = TransportMessageEnvelope.create(
            payload_type="command",
            payload={"prompt": "Ping"},
            channel="claude_channel",
        )
        self.assertTrue(transport.send(env))
        self.assertEqual(transport.sent_count, 1)

        resp = transport.receive(timeout=0.1)
        self.assertIsNotNone(resp)
        self.assertEqual(resp.payload_type, "response")
        self.assertEqual(resp.payload["reply"]["tokens"], 42)

    def test_rate_limit_detection_429(self):
        mock_client = MagicMock()
        mock_client.send.side_effect = Exception("HTTP 429: Resource has been exhausted (quota limit)")

        transport = ClaudeVertexTransport(mock_client=mock_client)
        transport.connect()

        env = TransportMessageEnvelope.create(
            payload_type="command",
            payload={"prompt": "Heavy workload"},
        )
        with self.assertRaises(TransportError) as ctx:
            transport.send(env)

        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        self.assertEqual(transport.rate_limit_count, 1)
        self.assertEqual(transport.status, TransportStatus.DEGRADED)

    def test_service_unavailable_503(self):
        mock_client = MagicMock()
        mock_client.send.side_effect = Exception("503 Service Temporarily Unavailable")

        transport = ClaudeVertexTransport(mock_client=mock_client)
        transport.connect()

        env = TransportMessageEnvelope.create(
            payload_type="command",
            payload={"prompt": "Test"},
        )
        with self.assertRaises(TransportError) as ctx:
            transport.send(env)

        self.assertEqual(ctx.exception.code, "SERVICE_UNAVAILABLE")
        self.assertEqual(transport.status, TransportStatus.DEGRADED)

    def test_tampered_envelope_rejected(self):
        mock_client = MagicMock()
        transport = ClaudeVertexTransport(mock_client=mock_client)
        transport.connect()

        env = TransportMessageEnvelope.create(
            payload_type="command",
            payload={"prompt": "Legitimate"},
        )
        # Нарушаем целостность
        env.payload["prompt"] = "Tampered"

        with self.assertRaises(TransportError) as ctx:
            transport.send(env)

        self.assertEqual(ctx.exception.code, "SIGNATURE_MISMATCH")


class TestFailoverRouter(unittest.TestCase):
    """Тесты каскадного роутера FailoverRouter."""

    def test_happy_path_primary_gemini(self):
        primary = DummyMockChannel("gemini_primary", should_fail=False)
        haiku = DummyMockChannel("claude_haiku", should_fail=False)
        router = FailoverRouter(primary_channel=primary, haiku_channel=haiku)
        self.assertTrue(router.connect())

        env = TransportMessageEnvelope.create(payload_type="command", payload={"query": "test"})
        self.assertTrue(router.send(env))

        self.assertFalse(router.fallback_active)
        self.assertEqual(router.current_tier, "primary")
        self.assertEqual(router.model_switches_total, 0)
        self.assertEqual(len(primary.history), 1)
        self.assertEqual(len(haiku.history), 0)

    def test_primary_429_triggers_claude_haiku(self):
        primary = DummyMockChannel("gemini_primary", should_fail=True, fail_code="RATE_LIMITED")
        haiku = DummyMockChannel("claude_haiku", should_fail=False)
        router = FailoverRouter(primary_channel=primary, haiku_channel=haiku)
        router.connect()

        env = TransportMessageEnvelope.create(payload_type="command", payload={"query": "test"})
        self.assertTrue(router.send(env))

        self.assertTrue(router.fallback_active)
        self.assertEqual(router.current_tier, "haiku")
        self.assertEqual(router.model_switches_total, 1)
        self.assertEqual(len(haiku.history), 1)

        # Ответ считывается из haiku
        resp = router.receive(timeout=0.1)
        self.assertIsNotNone(resp)
        self.assertEqual(resp.source, "claude_haiku")

    def test_haiku_failure_escalates_to_sonnet(self):
        primary = DummyMockChannel("gemini_primary", should_fail=True, fail_code="RATE_LIMITED")
        haiku = DummyMockChannel("claude_haiku", should_fail=True, fail_code="RATE_LIMITED")
        sonnet = DummyMockChannel("claude_sonnet", should_fail=False)

        router = FailoverRouter(
            primary_channel=primary,
            haiku_channel=haiku,
            sonnet_channel=sonnet,
        )
        router.connect()

        env = TransportMessageEnvelope.create(payload_type="command", payload={"query": "complex"})
        self.assertTrue(router.send(env))

        self.assertTrue(router.fallback_active)
        self.assertEqual(router.current_tier, "sonnet")
        self.assertEqual(router.model_switches_total, 2)
        self.assertEqual(len(sonnet.history), 1)

    def test_all_tiers_exhausted_fails_closed(self):
        primary = DummyMockChannel("gemini_primary", should_fail=True, fail_code="RATE_LIMITED")
        haiku = DummyMockChannel("claude_haiku", should_fail=True, fail_code="RATE_LIMITED")
        sonnet = DummyMockChannel("claude_sonnet", should_fail=True, fail_code="SERVICE_UNAVAILABLE")

        router = FailoverRouter(
            primary_channel=primary,
            haiku_channel=haiku,
            sonnet_channel=sonnet,
        )
        router.connect()

        env = TransportMessageEnvelope.create(payload_type="command", payload={"query": "all_down"})
        with self.assertRaises(TransportError) as ctx:
            router.send(env)

        self.assertEqual(ctx.exception.code, "FAILOVER_EXHAUSTED")

    def test_automatic_recovery_to_primary(self):
        primary = DummyMockChannel("gemini_primary", should_fail=True, fail_code="RATE_LIMITED")
        haiku = DummyMockChannel("claude_haiku", should_fail=False)
        router = FailoverRouter(primary_channel=primary, haiku_channel=haiku)
        router.connect()

        env1 = TransportMessageEnvelope.create(payload_type="command", payload={"query": "msg1"})
        router.send(env1)
        self.assertTrue(router.fallback_active)

        # Восстанавливаем primary
        primary.should_fail = False
        restored = router.check_and_restore_primary()
        self.assertTrue(restored)
        self.assertFalse(router.fallback_active)
        self.assertEqual(router.current_tier, "primary")
        self.assertEqual(router.model_switches_total, 2)  # 1 (to haiku) + 1 (back to primary)

        # Следующее сообщение должно идти в primary
        env2 = TransportMessageEnvelope.create(payload_type="command", payload={"query": "msg2"})
        self.assertTrue(router.send(env2))
        self.assertEqual(len(primary.history), 1)

    def test_metrics_snapshot(self):
        primary = DummyMockChannel("gemini_primary", should_fail=False)
        haiku = DummyMockChannel("claude_haiku", should_fail=False)
        local_gpu = DummyMockChannel("local_gpu_daemon", should_fail=False)
        router = FailoverRouter(primary_channel=primary, haiku_channel=haiku, local_gpu_channel=local_gpu)
        router.connect()

        metrics = router.get_metrics()
        self.assertEqual(metrics["model_switches_total"], 0)
        self.assertFalse(metrics["fallback_active"])
        self.assertEqual(metrics["current_tier"], "primary")
        self.assertEqual(metrics["primary_status"], "CONNECTED")
        self.assertEqual(metrics["local_gpu_status"], "CONNECTED")

    def test_cascade_to_local_gpu_when_cloud_exhausted(self):
        primary = DummyMockChannel("gemini_primary", should_fail=True, fail_code="RATE_LIMITED")
        haiku = DummyMockChannel("claude_haiku", should_fail=True, fail_code="SERVICE_UNAVAILABLE")
        sonnet = DummyMockChannel("claude_sonnet", should_fail=True, fail_code="RATE_LIMITED")
        local_gpu = DummyMockChannel("local_gpu_daemon", should_fail=False)

        router = FailoverRouter(
            primary_channel=primary,
            haiku_channel=haiku,
            sonnet_channel=sonnet,
            local_gpu_channel=local_gpu,
        )
        router.connect()

        env = TransportMessageEnvelope.create(payload_type="command", payload={"query": "test_gpu_fallback"})
        self.assertTrue(router.send(env))
        self.assertTrue(router.fallback_active)
        self.assertEqual(router.current_tier, "local_gpu")
        self.assertEqual(len(local_gpu.history), 1)

        resp = router.receive(timeout=0.1)
        self.assertIsNotNone(resp)
        self.assertEqual(resp.source, "local_gpu_daemon")

    def test_cascade_to_local_gpu_without_sonnet(self):
        primary = DummyMockChannel("gemini_primary", should_fail=True, fail_code="RATE_LIMITED")
        haiku = DummyMockChannel("claude_haiku", should_fail=True, fail_code="RATE_LIMITED")
        local_gpu = DummyMockChannel("local_gpu_daemon", should_fail=False)

        router = FailoverRouter(
            primary_channel=primary,
            haiku_channel=haiku,
            local_gpu_channel=local_gpu,
        )
        router.connect()

        env = TransportMessageEnvelope.create(payload_type="command", payload={"query": "direct_to_gpu"})
        self.assertTrue(router.send(env))
        self.assertEqual(router.current_tier, "local_gpu")
        self.assertEqual(len(local_gpu.history), 1)


if __name__ == "__main__":
    unittest.main()
