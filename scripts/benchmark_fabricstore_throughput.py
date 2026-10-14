# -*- coding: utf-8 -*-
"""
scripts.benchmark_fabricstore_throughput - Автономный стресс-тест и бенчмарк
пропускной способности очереди задач FabricStore и WorkerFleetScheduler (Stage R26).

Тестирует:
  1. Пакетную подачу 100+ параллельных задач в FabricStore;
  2. Пулинг и конкурентную диспетчеризацию через WorkerFleetScheduler;
  3. Замер P50, P90, P95, P99 задержек диспетчеризации и общего throughput (задач/сек);
  4. Инвариант нулевой потери задач (100% PASS, 0 LOST).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF 10.8 Stage R26 [Класс C - Y].
"""

from __future__ import annotations

__version__ = "1.0.0"

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from rai_fabric.store import FabricStore
from rai_fabric.scheduler import WorkerFleetScheduler, SchedulerConfig


def run_throughput_benchmark(
    task_count: int = 120,
    worker_count: int = 12,
    db_path: Path | None = None,
) -> Dict[str, Any]:
    """Выполняет автономный бенчмарк пропускной способности FabricStore."""
    if db_path is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="raif_benchmark_"))
        db_file = temp_dir / "bench_store.sqlite3"
    else:
        temp_dir = db_path.parent
        db_file = db_path

    store = FabricStore(db_file, initialize=True)

    cfg = SchedulerConfig(
        poll_interval_seconds=0.01,
        max_concurrent_workers=worker_count,
        default_lease_seconds=30,
    )
    scheduler = WorkerFleetScheduler(store, config=cfg)

    # 1. Регистрация пула воркеров
    for i in range(worker_count):
        scheduler.register_worker(f"BenchWorker-{i:02d}", "mock", worker_id=f"w-bench-{i:02d}")

    # 2. Подача пакета задач с замером времени вставки
    t_submit_start = time.perf_counter()
    task_ids: List[str] = []
    for i in range(task_count):
        tid = f"bench-task-{i:04d}"
        store.submit(
            objective=f"Стресс-тестовая синтетическая задача #{i}",
            provider="mock",
            workspace=str(temp_dir),
            task_id=tid,
        )
        task_ids.append(tid)
    submit_duration_sec = time.perf_counter() - t_submit_start
    submit_rate = task_count / max(submit_duration_sec, 0.0001)

    # 3. Диспетчеризация и замер латентности
    t_dispatch_start = time.perf_counter()
    ticks = 0
    dispatched_total = 0
    tick_latencies_ms: List[float] = []

    while dispatched_total < task_count:
        ticks += 1
        t_tick = time.perf_counter()
        res = scheduler.tick()
        tick_latencies_ms.append((time.perf_counter() - t_tick) * 1000.0)

        dispatched = res.get("dispatched_count", 0)
        dispatched_total += dispatched

        if dispatched == 0:
            # Проверяем оставшиеся в очереди
            pending = store.db.execute("SELECT count(*) as cnt FROM tasks WHERE status='QUEUED'").fetchone()["cnt"]
            if pending == 0:
                break
            time.sleep(0.005)

    dispatch_duration_sec = time.perf_counter() - t_dispatch_start
    throughput_rate = task_count / max(dispatch_duration_sec, 0.0001)

    # 4. Проверка консистентности и статусов задач
    completed_count = store.db.execute("SELECT count(*) as cnt FROM tasks WHERE status='COMPLETE'").fetchone()["cnt"]
    failed_count = store.db.execute("SELECT count(*) as cnt FROM tasks WHERE status='FAILED'").fetchone()["cnt"]
    queued_count = store.db.execute("SELECT count(*) as cnt FROM tasks WHERE status='QUEUED'").fetchone()["cnt"]

    sorted_latencies = sorted(tick_latencies_ms)
    p50 = sorted_latencies[len(sorted_latencies) // 2] if sorted_latencies else 0.0
    p90 = sorted_latencies[int(len(sorted_latencies) * 0.90)] if sorted_latencies else 0.0
    p95 = sorted_latencies[int(len(sorted_latencies) * 0.95)] if sorted_latencies else 0.0
    p99 = sorted_latencies[int(len(sorted_latencies) * 0.99)] if sorted_latencies else 0.0

    report = {
        "status": "PASS" if completed_count == task_count and failed_count == 0 else "FAIL",
        "benchmark": "FabricStore_WorkerFleetScheduler_Throughput",
        "task_count": task_count,
        "worker_count": worker_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "queued_remaining": queued_count,
        "submit_duration_ms": round(submit_duration_sec * 1000.0, 2),
        "submit_rate_tasks_per_sec": round(submit_rate, 2),
        "dispatch_duration_ms": round(dispatch_duration_sec * 1000.0, 2),
        "throughput_tasks_per_sec": round(throughput_rate, 2),
        "ticks_count": ticks,
        "latency_p50_ms": round(p50, 3),
        "latency_p90_ms": round(p90, 3),
        "latency_p95_ms": round(p95, 3),
        "latency_p99_ms": round(p99, 3),
        "zero_loss_guarantee": completed_count == task_count,
        "timestamp": time.time(),
    }

    store.close()
    return report


def main() -> int:
    print("=" * 72)
    print("⚡ [STAGE R26] АВТОНОМНЫЙ БЕНЧМАРК ПРОПУСКНОЙ СПОСОБНОСТИ FABRICSTORE (120 ЗАДАЧ)")
    print("=" * 72)
    report = run_throughput_benchmark(task_count=120, worker_count=12)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    receipt_path = REPO_ROOT / "docs" / "STAGE_R26_BENCHMARK_THROUGHPUT_RECEIPT.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n[OK] Квитанция сохранена: {receipt_path.name}")
    print("=" * 72)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
