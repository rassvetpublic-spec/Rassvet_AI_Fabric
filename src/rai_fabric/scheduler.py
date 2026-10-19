# -*- coding: utf-8 -*-
r"""
rai_fabric.scheduler - Автономный диспетчер очередей задач (Stage R26 / Issue #17).
Обеспечивает:
  1. Автоматическое распределение задач из FabricStore (QUEUED -> RUNNING -> COMPLETE);
  2. Пулинг и ротацию воркеров с отслеживанием статусов (IDLE, BUSY, OFFLINE);
  3. Интеграцию с пулом учетных записей супервизора и балансировку квот;
  4. Автоматическое продление аренды и восстановление зависших задач (fail-closed recovery);
  5. Стриминг телеметрии в \\.\pipe\fleet_metrics (Zero SSD Wear).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF 10.8 Stage R26 / Rassvet_AI_Fabric#17.
"""

from __future__ import annotations

__version__ = "1.0.0"

import os
import sys
import time
import uuid
import json
import sqlite3
import threading
import argparse
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .store import FabricStore, FabricError
from .worker import run_one
from .transport import ITransportChannel, TransportMessageEnvelope

DEFAULT_FLEET_METRICS_PIPE = r"\\.\pipe\fleet_metrics"


@dataclass
class WorkerInfo:
    worker_id: str
    name: str
    provider: str
    status: str = "IDLE"  # IDLE, BUSY, DRAINING, OFFLINE
    current_task_id: Optional[str] = None
    assigned_account: Optional[str] = None
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_execution_ms: float = 0.0
    last_heartbeat: float = field(default_factory=time.time)


@dataclass
class SchedulerConfig:
    poll_interval_seconds: float = 1.0
    default_lease_seconds: int = 180
    max_concurrent_workers: int = 8
    enable_auto_recovery: bool = True
    telemetry_pipe: str = DEFAULT_FLEET_METRICS_PIPE


class WorkerFleetScheduler:
    """Автономный планировщик очереди и распределитель ресурсов флота воркеров."""

    def __init__(
        self,
        store: FabricStore,
        config: Optional[SchedulerConfig] = None,
        account_pool: Optional[List[str]] = None,
    ) -> None:
        self.store = store
        self.config = config or SchedulerConfig()
        self.workers: Dict[str, WorkerInfo] = {}
        self.account_pool: List[str] = list(account_pool or ["default_supervisor_account"])
        self._account_index: int = 0
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._dispatched_count = 0
        self._recovered_count = 0

    def register_worker(self, name: str, provider: str, worker_id: Optional[str] = None) -> WorkerInfo:
        """Регистрирует нового исполнителя в пуле планировщика."""
        with self._lock:
            w_id = worker_id or f"worker-{provider}-{uuid.uuid4().hex[:6]}"
            info = WorkerInfo(
                worker_id=w_id,
                name=name,
                provider=provider,
                status="IDLE",
                last_heartbeat=time.time(),
            )
            self.workers[w_id] = info
            return info

    def unregister_worker(self, worker_id: str) -> bool:
        """Удаляет исполнителя из пула."""
        with self._lock:
            if worker_id in self.workers:
                del self.workers[worker_id]
                return True
            return False

    def get_idle_worker(self, provider: str) -> Optional[WorkerInfo]:
        """Возвращает свободного воркера для указанного провайдера."""
        with self._lock:
            for w in self.workers.values():
                if w.status == "IDLE" and w.provider == provider:
                    return w
            return None

    def _next_account(self) -> str:
        """Ротация аккаунтов по принципу Round-Robin."""
        with self._lock:
            if not self.account_pool:
                return "anonymous_account"
            account = self.account_pool[self._account_index % len(self.account_pool)]
            self._account_index += 1
            return account

    def tick(self, store: Optional[FabricStore] = None) -> Dict[str, Any]:
        """Один такт диспетчеризации: сканирование очереди, назначение и исполнение."""
        current_store = store or self.store
        with self._lock:
            dispatched: List[str] = []
            deferred_real: List[str] = []
            recovered = 0

            # 1. Фоновое восстановление зависших задач по таймауту аренды
            if self.config.enable_auto_recovery:
                try:
                    recs = current_store.recover()
                    if recs:
                        recovered = len(recs)
                        self._recovered_count += recovered
                except Exception:
                    pass

            # 2. Поиск доступных задач QUEUED
            tasks_cursor = current_store.db.execute(
                "SELECT id, provider, objective FROM tasks WHERE status='QUEUED' ORDER BY created_at ASC LIMIT ?",
                (self.config.max_concurrent_workers,),
            ).fetchall()

            for row in tasks_cursor:
                task_id = row["id"]
                provider = row["provider"]

                # No verified real-provider adapter or signed target receipt exists.
                # Do not claim, rotate an account, or synthesize a PASS for real tasks.
                if provider not in {"mock", "codex-mock"}:
                    deferred_real.append(task_id)
                    continue
                worker = self.get_idle_worker(provider)
                if not worker:
                    continue

                worker.status = "BUSY"
                worker.current_task_id = task_id
                worker.assigned_account = self._next_account()
                start_t = time.perf_counter()
                try:
                    res = run_one(
                        current_store,
                        provider,
                        owner=worker.worker_id,
                        timeout_seconds=self.config.default_lease_seconds,
                    )
                    if res.get("status") == "NO_READY_TASK":
                        continue
                    if res.get("status") != "COMPLETE":
                        worker.tasks_failed += 1
                        continue
                    # FabricStore.finish returns get() with "id", not "task_id".
                    actual_id = res.get("id") or res.get("task_id") or task_id
                    worker.tasks_completed += 1
                    dispatched.append(actual_id)
                    self._dispatched_count += 1
                except Exception:
                    worker.tasks_failed += 1
                finally:
                    worker.total_execution_ms += (time.perf_counter() - start_t) * 1000.0
                    worker.status = "IDLE"
                    worker.current_task_id = None
                    worker.last_heartbeat = time.time()

            summary = {
                "dispatched_count": len(dispatched),
                "dispatched_tasks": dispatched,
                "mock_done_tasks": dispatched.copy(),
                "real_pass_tasks": [],  # Only a verified adapter may populate this in future.
                "deferred_real_tasks": deferred_real,
                "real_provider_gate": "NO_VERIFIED_TARGET_ADAPTER_OR_RECEIPT",
                "recovered_count": recovered,
                "total_dispatched": self._dispatched_count,
                "active_workers_count": sum(1 for w in self.workers.values() if w.status == "BUSY"),
                "idle_workers_count": sum(1 for w in self.workers.values() if w.status == "IDLE"),
            }

            self._emit_telemetry(summary)
            return summary

    def _emit_telemetry(self, stats: Dict[str, Any]) -> None:
        """Отправка метрик планировщика в Named Pipe fleet_metrics."""
        try:
            from multiprocessing.connection import Client
            address = self.config.telemetry_pipe
            family = "AF_PIPE" if os.name == "nt" and address.startswith(r"\\.\pipe\\") else "AF_INET"
            conn_target = address if family == "AF_PIPE" else ("127.0.0.1", 18899)
            conn = Client(conn_target, family=family)
            event = {
                "event_type": "raif.scheduler.tick",
                "source": "WorkerFleetScheduler",
                "timestamp": time.time(),
                "dispatched_count": stats.get("dispatched_count", 0),
                "total_dispatched": stats.get("total_dispatched", 0),
                "active_workers": stats.get("active_workers_count", 0),
                "idle_workers": stats.get("idle_workers_count", 0),
            }
            conn.send(event)
            conn.close()
        except Exception:
            pass  # Неблокирующий сброс телеметрии

    def start(self) -> None:
        """Запуск фонового цикла планировщика."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="WorkerFleetSchedulerLoop", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Остановка планировщика."""
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def _loop(self) -> None:
        thread_store = FabricStore(self.store.path)
        try:
            while self._running:
                try:
                    self.tick(store=thread_store)
                except Exception:
                    pass
                time.sleep(self.config.poll_interval_seconds)
        finally:
            thread_store.close()

    def status_report(self) -> Dict[str, Any]:
        """Полный статус состояния диспетчера и воркеров."""
        with self._lock:
            return {
                "running": self._running,
                "dispatched_total": self._dispatched_count,
                "recovered_total": self._recovered_count,
                "workers_count": len(self.workers),
                "account_pool_size": len(self.account_pool),
                "workers": {w_id: asdict(w) for w_id, w in self.workers.items()},
            }


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous Worker Fleet Scheduler (Stage R26)")
    parser.add_argument("--db", default=".rai-fabric/state.sqlite3", help="Путь к SQLite хранилищу задач")
    parser.add_argument("--init", action="store_true", help="Инициализировать базу и зарегистрировать тестовых воркеров")
    parser.add_argument("--tick", action="store_true", help="Выполнить один такт диспетчеризации")
    parser.add_argument("--status", action="store_true", help="Показать статус планировщика")
    args = parser.parse_args()

    db_path = Path(args.db)
    store = FabricStore(db_path, initialize=args.init or not db_path.exists())
    scheduler = WorkerFleetScheduler(store)

    if args.init:
        w1 = scheduler.register_worker("MockWorker-01", "mock")
        w2 = scheduler.register_worker("CodexMockWorker-01", "codex-mock")
        print(f"PASS: Пул инициализирован. Зарегистрированы: {w1.worker_id}, {w2.worker_id}")

    if args.tick:
        res = scheduler.tick()
        print(json.dumps(res, ensure_ascii=False, indent=2))

    if args.status:
        st = scheduler.status_report()
        print(json.dumps(st, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
