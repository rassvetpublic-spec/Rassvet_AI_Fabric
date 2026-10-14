# -*- coding: utf-8 -*-
"""
tests.test_scheduler_throughput - Автоматический тест пропускной способности очереди
FabricStore и WorkerFleetScheduler (Stage R26).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from benchmark_fabricstore_throughput import run_throughput_benchmark


def test_scheduler_throughput_batch(tmp_path: Path):
    """Стресс-тест очереди на 30 задач с 6 воркерами: 100% завершение, 0 потерь."""
    db_file = tmp_path / "test_throughput.sqlite3"
    report = run_throughput_benchmark(task_count=30, worker_count=6, db_path=db_file)
    assert report["status"] == "PASS"
    assert report["completed_count"] == 30
    assert report["failed_count"] == 0
    assert report["queued_remaining"] == 0
    assert report["zero_loss_guarantee"] is True
