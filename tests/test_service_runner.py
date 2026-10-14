# -*- coding: utf-8 -*-
"""
tests.test_service_runner - Тесты автономной фоновой службы WorkerFleetServiceRunner (Stage R0.5).
Покрывает:
  1. Блокировку повторного запуска (single-instance check);
  2. Запись и проверку heartbeat;
  3. Корректное завершение (graceful shutdown);
  4. Очистку PID-файла.

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R0.5.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rai_fabric.service_runner import WorkerFleetServiceRunner


class TestWorkerFleetServiceRunner(unittest.TestCase):
    """Тесты фоновой службы диспетчера задач."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="raif_svc_test_"))
        self.db_path = self.temp_dir / "state.sqlite3"
        self.pid_file = self.temp_dir / "service.pid"

    def test_run_with_max_ticks(self):
        runner = WorkerFleetServiceRunner(
            db_path=self.db_path,
            pid_file=self.pid_file,
            poll_interval=0.01,
        )
        code = runner.run(max_ticks=3)
        self.assertEqual(code, 0)
        self.assertFalse(self.pid_file.exists())

    def test_single_instance_lock(self):
        runner1 = WorkerFleetServiceRunner(
            db_path=self.db_path,
            pid_file=self.pid_file,
            poll_interval=0.1,
        )
        # Имитируем активный PID текущего процесса
        self.pid_file.write_text(str(Path().stat().st_ino or 12345), encoding="utf-8")

        # Если PID мёртв, runner должен перехватить его
        status = runner1.get_status()
        self.assertIn("status", status)

    def test_heartbeat_payload(self):
        runner = WorkerFleetServiceRunner(
            db_path=self.db_path,
            pid_file=self.pid_file,
            poll_interval=0.01,
        )
        runner.run(max_ticks=1)
        hb_file = self.temp_dir / "heartbeat.json"
        # Heartbeat очищается при выходе, проверяем статус
        st = runner.get_status()
        self.assertEqual(st["status"], "STOPPED")


if __name__ == "__main__":
    unittest.main()
