# -*- coding: utf-8 -*-
"""Unit-тесты для Autonomous Worker Fleet Scheduler (Stage R26 / Rassvet_AI_Fabric#17)."""

import os
import time
import pytest
from pathlib import Path

from rai_fabric.store import FabricStore
from rai_fabric.scheduler import WorkerFleetScheduler, SchedulerConfig, WorkerInfo


@pytest.fixture
def temp_store(tmp_path: Path):
    db_file = tmp_path / "scheduler_test.sqlite3"
    store = FabricStore(db_file, initialize=True)
    yield store
    store.close()


def test_scheduler_worker_registration(temp_store):
    scheduler = WorkerFleetScheduler(temp_store)
    worker = scheduler.register_worker("TestWorker-01", "mock")
    assert worker.worker_id.startswith("worker-mock-")
    assert worker.status == "IDLE"

    idle = scheduler.get_idle_worker("mock")
    assert idle is not None
    assert idle.worker_id == worker.worker_id

    # Unregister
    assert scheduler.unregister_worker(worker.worker_id) is True
    assert scheduler.get_idle_worker("mock") is None


def test_scheduler_task_dispatch_fifo(temp_store, tmp_path: Path):
    # Один воркер и один слот на такт: порядок двух задач проверяется наблюдаемо.
    scheduler = WorkerFleetScheduler(
        temp_store, config=SchedulerConfig(max_concurrent_workers=1)
    )
    scheduler.register_worker("MockWorker-01", "mock")

    first = temp_store.submit(
        objective="Первая задача FIFO",
        provider="mock",
        workspace=str(tmp_path),
        task_id="fifo-z-first",
    )
    second = temp_store.submit(
        objective="Вторая задача FIFO",
        provider="mock",
        workspace=str(tmp_path),
        task_id="fifo-a-second",
    )
    # Устраняем зависимость порядка от разрешения часов Windows.
    with temp_store.atomic():
        temp_store.db.execute(
            "UPDATE tasks SET created_at=? WHERE id=?",
            (100.0, first["id"]),
        )
        temp_store.db.execute(
            "UPDATE tasks SET created_at=? WHERE id=?",
            (200.0, second["id"]),
        )

    first_tick = scheduler.tick()
    assert first_tick["dispatched_count"] == 1
    assert first_tick["dispatched_tasks"] == [first["id"]]
    assert temp_store.get(first["id"])["status"] == "COMPLETE"
    assert temp_store.get(second["id"])["status"] == "QUEUED"

    second_tick = scheduler.tick()
    assert second_tick["dispatched_count"] == 1
    assert second_tick["dispatched_tasks"] == [second["id"]]
    assert temp_store.get(second["id"])["status"] == "COMPLETE"

    for task_id in (first["id"], second["id"]):
        row = temp_store.db.execute(
            "SELECT result_json FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert row is not None
        assert "Имитатор принял задачу" in row[0]


def test_scheduler_account_rotation(temp_store):
    accounts = ["account_alpha@google.com", "account_beta@google.com", "account_gamma@google.com"]
    scheduler = WorkerFleetScheduler(temp_store, account_pool=accounts)
    
    assert scheduler._next_account() == "account_alpha@google.com"
    assert scheduler._next_account() == "account_beta@google.com"
    assert scheduler._next_account() == "account_gamma@google.com"
    assert scheduler._next_account() == "account_alpha@google.com"


def test_scheduler_status_report(temp_store):
    scheduler = WorkerFleetScheduler(temp_store)
    scheduler.register_worker("Worker-A", "mock")
    scheduler.register_worker("Worker-B", "codex-mock")

    report = scheduler.status_report()
    assert report["workers_count"] == 2
    assert report["running"] is False
    assert "dispatched_total" in report


def test_scheduler_lifecycle(temp_store):
    config = SchedulerConfig(poll_interval_seconds=0.1)
    scheduler = WorkerFleetScheduler(temp_store, config=config)
    scheduler.register_worker("Worker-Loop", "mock")

    scheduler.start()
    assert scheduler.status_report()["running"] is True

    # Submit task while running
    task = temp_store.submit(objective="Фоновая задача", provider="mock", workspace=".")
    
    # Ожидание обработки планировщиком
    for _ in range(30):
        if temp_store.get(task["id"])["status"] == "COMPLETE":
            break
        time.sleep(0.1)

    assert temp_store.get(task["id"])["status"] == "COMPLETE"

    scheduler.stop()
    assert scheduler.status_report()["running"] is False
