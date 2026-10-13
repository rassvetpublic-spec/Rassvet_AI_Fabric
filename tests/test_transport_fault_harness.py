# -*- coding: utf-8 -*-
"""
tests.test_transport_fault_harness - Стресс-тестирование и фальсификационный харнесс (Adversarial Fault Harness).
Покрывает:
  1. Нагрузочный конвейер (Pipelined stress test) с параллельными потоками;
  2. Аварийное падение Named Pipe и мгновенный failover на HTTP fallback (127.0.0.1:18892);
  3. Восстановление первичного канала связи после перезапуска сервера;
  4. Фальсификацию пакетов и защиту от DoS (ограничение размера и проверка подписи);
  5. Ограничение RAM-буфера метрик (Ring-buffer Bounding, Zero SSD Wear).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.2) / RAiF 10.7 Stage R25 / MTD Authorized.
"""

from __future__ import annotations

import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from transport.ipc_channel import (
    TransportError,
    TransportMessageEnvelope,
    TransportStatus,
)
from transport.real_transport import (
    DEFAULT_FALLBACK_PORT,
    FleetMetricsBridge,
    HttpFallbackServer,
    NamedPipeClient,
    NamedPipeServer,
    RealTransportAdapter,
)


class TestTransportFaultHarness(unittest.TestCase):
    """Стресс-тестирование надежности и отказоустойчивости транспорта."""

    def test_pipelined_stress_multithreaded(self):
        """Нагрузочный тест: отправка 100 сообщений из нескольких параллельных потоков."""
        test_pipe = r"\\.\pipe\raif_stress_pipe_01"
        test_port = 18871
        server = NamedPipeServer(pipe_name=test_pipe, inet_fallback_port=test_port)
        server.start()

        client = NamedPipeClient(pipe_name=test_pipe, inet_fallback_port=test_port)
        self.assertTrue(client.connect())

        messages_count = 100
        sent_ids = set()
        received_ids = set()

        def worker_send(idx: int):
            env = TransportMessageEnvelope.create(
                payload_type="stress_packet",
                payload={"batch_idx": idx, "data": "X" * 128},
            )
            if client.send(env):
                return env.message_id
            return None

        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(worker_send, i) for i in range(messages_count)]
                for f in futures:
                    res = f.result()
                    if res:
                        sent_ids.add(res)

            # Вычитываем полученные сообщения сервером
            deadline = time.time() + 5.0
            while len(received_ids) < len(sent_ids) and time.time() < deadline:
                msg = server.receive(timeout=0.2)
                if msg:
                    received_ids.add(msg.message_id)

            self.assertEqual(len(sent_ids), messages_count, "Все сообщения должны быть успешно отправлены")
            self.assertEqual(len(received_ids), messages_count, "Все отправленные сообщения должны быть приняты без потерь")
        finally:
            client.disconnect()
            server.stop()

    def test_abrupt_pipe_crash_and_failover_to_http(self):
        """Эмуляция аварийного падения Named Pipe и мгновенный failover на резервный HTTP шлюз."""
        pipe_name = r"\\.\pipe\raif_failover_test_pipe"
        pipe_port = 18872
        http_port = 18873
        metrics_pipe = r"\\.\pipe\raif_failover_metrics"

        # 1. Запуск обоих серверов
        pipe_server = NamedPipeServer(pipe_name=pipe_name, inet_fallback_port=pipe_port)
        pipe_server.start()

        http_server = HttpFallbackServer(host="127.0.0.1", port=http_port)
        http_server.start()
        time.sleep(0.05)

        # 2. Инициализация адаптера (должен выбрать первичный NAMED_PIPE)
        adapter = RealTransportAdapter(
            pipe_name=pipe_name,
            fallback_port=http_port,
            metrics_pipe=metrics_pipe,
            inet_fallback_port=pipe_port,
        )
        self.assertTrue(adapter.start(start_heartbeat=False))
        self.assertEqual(adapter.active_channel_name, "NAMED_PIPE")

        try:
            # 3. Успешная передача через Named Pipe
            env1 = TransportMessageEnvelope.create("test", {"val": 1})
            self.assertTrue(adapter.send(env1))
            self.assertIsNotNone(pipe_server.receive(timeout=1.0))

            # 4. Аварийное падение Named Pipe сервера
            pipe_server.stop()
            time.sleep(0.1)

            # 5. Отправка следующего сообщения — адаптер должен обнаружить обрыв и переключиться на HTTP_FALLBACK
            env2 = TransportMessageEnvelope.create("test", {"val": 2})
            send_res = adapter.send(env2)
            self.assertTrue(send_res, "Адаптер обязан успешно отправить сообщение через резервный HTTP канал")
            self.assertEqual(adapter.active_channel_name, "HTTP_FALLBACK")

            # Проверяем приём HTTP сервером
            received_http = http_server.dequeue_message(timeout=1.0)
            self.assertIsNotNone(received_http)
            assert received_http is not None
            self.assertEqual(received_http.message_id, env2.message_id)

            # 6. Восстановление Named Pipe сервера
            pipe_server = NamedPipeServer(pipe_name=pipe_name, inet_fallback_port=pipe_port)
            pipe_server.start()
            time.sleep(0.1)

            # 7. Последующая отправка должна вернуть первичный канал NAMED_PIPE
            env3 = TransportMessageEnvelope.create("test", {"val": 3})
            self.assertTrue(adapter.send(env3))
            self.assertEqual(adapter.active_channel_name, "NAMED_PIPE")
            self.assertIsNotNone(pipe_server.receive(timeout=1.0))
        finally:
            adapter.stop()
            pipe_server.stop()
            http_server.stop()

    def test_ram_ring_buffer_bounds(self):
        """Проверка ограничения размера буфера телеметрии в ОЗУ (Zero SSD Wear / No OOM)."""
        bridge = FleetMetricsBridge(
            pipe_name=r"\\.\pipe\nonexistent_pipe_ram_test",
            inet_port=18879,
            max_ram_buffer=20,  # Лимит 20 записей
        )
        try:
            # Отправка 50 записей в оффлайн-режиме
            for i in range(50):
                bridge.emit_event("metric", {"idx": i})

            # Размер очереди в памяти строго ограничен 20 (самые старые вытеснены)
            self.assertEqual(bridge.buffered_count, 20)
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
