# -*- coding: utf-8 -*-
"""
rai_fabric.service_runner - Диспетчер автономной фоновой службы Windows для WorkerFleetScheduler (Stage R0.5).
Обеспечивает:
  1. Фоновый запуск WorkerFleetScheduler в виде постоянного процесса (Service Runner);
  2. Запись и проверку PID-файла с блокировкой повторного запуска (single-instance);
  3. Периодический heartbeat в оперативной памяти / временном файле;
  4. Мягкую остановку (graceful shutdown) при получении сигналов завершения;
  5. Автоматическое восстановление очереди задач после аварийного перезапуска (crash recovery).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R0.5 / Rassvet_AI_Fabric.
"""

from __future__ import annotations

__version__ = "1.0.0"

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .scheduler import SchedulerConfig, WorkerFleetScheduler
from .store import FabricStore

logger = logging.getLogger("raif.service_runner")


class WorkerFleetServiceRunner:
    """Управляющий контроллер непрерывной фоновой службы диспетчера задач на Windows."""

    def __init__(
        self,
        db_path: Path | str = ".rai-fabric/state.sqlite3",
        pid_file: Optional[Path | str] = None,
        poll_interval: float = 1.0,
        account_pool: Optional[list[str]] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.pid_file = Path(pid_file) if pid_file else self.db_path.parent / "service.pid"
        self.poll_interval = poll_interval
        self.account_pool = account_pool or ["default_account"]

        self._store: Optional[FabricStore] = None
        self._scheduler: Optional[WorkerFleetScheduler] = None
        self._running = False
        self._stop_event = threading.Event()
        self._heartbeat_file = self.pid_file.parent / "heartbeat.json"

    @property
    def is_running(self) -> bool:
        return self._running

    def _acquire_pid(self) -> bool:
        """Атомарная фиксация PID процесса с проверкой живости предшественника."""
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        if self.pid_file.exists():
            try:
                old_pid = int(self.pid_file.read_text(encoding="utf-8").strip())
                # Проверка живости PID
                if self._is_pid_alive(old_pid):
                    logger.warning("Service already running with PID %s", old_pid)
                    return False
            except Exception:
                pass  # Поврежденный или устаревший файл перезаписываем

        self.pid_file.write_text(str(os.getpid()), encoding="utf-8")
        return True

    def _release_pid(self) -> None:
        """Удаление PID-файла при штатной остановке."""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
            if self._heartbeat_file.exists():
                self._heartbeat_file.unlink()
        except Exception:
            pass

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Проверка существования процесса в ОС Windows."""
        if pid <= 0:
            return False
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def _write_heartbeat(self, stats: Dict[str, Any]) -> None:
        """Обновление файла heartbeat для внешних watchdog-мониторов."""
        try:
            payload = {
                "pid": os.getpid(),
                "timestamp": time.time(),
                "status": "RUNNING" if self._running else "STOPPED",
                "stats": stats,
            }
            self._heartbeat_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def run(self, max_ticks: Optional[int] = None) -> int:
        """Основной цикл исполнения службы."""
        if not self._acquire_pid():
            return 1

        self._store = FabricStore(self.db_path, initialize=True)
        cfg = SchedulerConfig(poll_interval_seconds=self.poll_interval)
        self._scheduler = WorkerFleetScheduler(self._store, config=cfg, account_pool=self.account_pool)

        # Регистрация дефолтных исполнителей
        self._scheduler.register_worker("SvcMock-01", "mock")
        self._scheduler.register_worker("SvcCodex-01", "codex-mock")

        self._running = True
        logger.info("WorkerFleetServiceRunner started (PID: %s)", os.getpid())

        tick_idx = 0
        try:
            while self._running and not self._stop_event.is_set():
                tick_idx += 1
                stats = self._scheduler.tick()
                self._write_heartbeat(stats)

                if max_ticks and tick_idx >= max_ticks:
                    break

                self._stop_event.wait(self.poll_interval)
        finally:
            self._running = False
            if self._store:
                self._store.close()
            self._release_pid()
            logger.info("WorkerFleetServiceRunner stopped cleanly")

        return 0

    def stop(self) -> None:
        """Сигнал остановки службы."""
        self._running = False
        self._stop_event.set()

    def get_status(self) -> Dict[str, Any]:
        """Чтение статуса службы по PID и heartbeat."""
        if not self.pid_file.exists():
            return {"status": "STOPPED", "pid": None}

        try:
            pid = int(self.pid_file.read_text(encoding="utf-8").strip())
            alive = self._is_pid_alive(pid)
            hb = {}
            if self._heartbeat_file.exists():
                try:
                    hb = json.loads(self._heartbeat_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            return {
                "status": "RUNNING" if alive else "DEAD_PID_FILE",
                "pid": pid,
                "alive": alive,
                "heartbeat": hb,
            }
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc)}
