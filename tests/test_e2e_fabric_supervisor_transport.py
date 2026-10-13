# -*- coding: utf-8 -*-
"""
tests.test_e2e_fabric_supervisor_transport - Сквозной интеграционный тест (E2E Integration).
Проверяет непрерывный конвейер взаимодействия:
  1. Antigravity UnifiedSupervisor (привязка Google-аккаунта в RAM через ASTRA-роутинг);
  2. Боевой IPC-транспорт RealTransportAdapter (Named Pipe \\\\.\\pipe\\raif_transport);
  3. Маршрутизация запросов к моделям и трансляция статусов в CONTROL_TOWER;
  4. Потоковый мост телеметрии FleetMetricsBridge (Zero SSD Wear).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.2) / RAiF 10.7 Stage R25 / MTD Authorized.
"""

from __future__ import annotations

import os
import time
import unittest
from pathlib import Path

from raif_ag_supervisor.unified_supervisor import (
    UnifiedSupervisor,
    AstraRoutingMechanism,
    BinaryPatchMechanism,
)
from transport.ipc_channel import (
    TransportMessageEnvelope,
    TransportStatus,
)
from transport.real_transport import (
    NamedPipeServer,
    NamedPipeClient,
    FleetMetricsBridge,
    RealTransportAdapter,
)


class TestE2EFabricSupervisorTransport(unittest.TestCase):
    """Сквозное тестирование конвейера генерации, диспетчеризации и транспорта."""

    def setUp(self):
        self.test_pipe = r"\\.\pipe\raif_e2e_pipeline_test"
        self.test_port = 18886
        self.fallback_port = 18887
        self.metrics_pipe = r"\\.\pipe\raif_e2e_metrics_test"

        # Запуск принимающего сервера флота
        self.server = NamedPipeServer(
            pipe_name=self.test_pipe,
            inet_fallback_port=self.test_port,
        )
        self.server.start()

        # Инициализация адаптера
        self.adapter = RealTransportAdapter(
            pipe_name=self.test_pipe,
            fallback_port=self.fallback_port,
            metrics_pipe=self.metrics_pipe,
            inet_fallback_port=self.test_port,
        )
        self.adapter.start(start_heartbeat=False)

    def tearDown(self):
        self.adapter.stop()
        self.server.stop()

    def test_end_to_end_pipeline(self):
        # 1. Инициализация UnifiedSupervisor
        supervisor = UnifiedSupervisor()
        self.assertIsNotNone(supervisor.bin_patch)
        self.assertIsNotNone(supervisor.astra_routing)

        # 2. Мгновенная привязка сессии в RAM без перезапуска процесса (ASTRA Routing)
        session_id = "sess_e2e_20261013"
        account_id = "acc_primary_developer"
        bind_res = supervisor.astra_routing.bind_session(session_id, account_id)
        self.assertEqual(bind_res["status"], "BOUND")
        self.assertEqual(supervisor.astra_routing.get_session_account(session_id), account_id)

        # 3. Формирование агрегированного статуса супервизора
        status_report = {
            "session_id": session_id,
            "account_id": account_id,
            "patch_status": "SIGNATURE_VERIFIED",
            "active_mode": "ASTRA_RAM_ROUTING",
            "quota_status": "NORMAL",
            "timestamp": time.time(),
        }

        # 4. Отправка статуса супервизора через RealTransportAdapter в канал флота
        sent_status = self.adapter.register_supervisor_status(status_report)
        self.assertTrue(sent_status, "Статус супервизора должен успешно передаваться")

        # 5. Приём сервером и криптографическая проверка подписи
        envelope = self.server.receive(timeout=3.0)
        self.assertIsNotNone(envelope, "Сервер должен получить конверт сообщения")
        assert envelope is not None
        self.assertEqual(envelope.payload_type, "supervisor_status")
        self.assertEqual(envelope.payload["session_id"], session_id)
        self.assertTrue(envelope.verify_signature(), "SHA-256 подпись конверта обязана быть подлинной")

        # 6. Маршрутизация запроса к модели через адаптер
        routing_receipt = self.adapter.route_model_request(
            target_account=account_id,
            prompt="Генерация AST-паспорта BPR40 для нового модуля",
            session_id=session_id,
        )
        self.assertTrue(routing_receipt["routed"])
        self.assertEqual(routing_receipt["target_account"], account_id)

        # 7. Проверка буферизации телеметрии в FleetMetricsBridge (Zero SSD Wear)
        self.assertGreaterEqual(self.adapter.metrics_bridge.buffered_count, 1)


if __name__ == "__main__":
    unittest.main()
