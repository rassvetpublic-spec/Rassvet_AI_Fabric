# -*- coding: utf-8 -*-
"""
scripts/stress_distributed_pool.py - Сквозной стресс-тест пула воркеров DistributedWorkerPool с реальным GPU-инференсом (Stage R0.6).

Обеспечивает:
  1. Регистрацию пула параллельных виртуальных воркеров (worker-gpu-01 .. worker-gpu-N);
  2. Параллельную подачу пакета задач (batch size = 20) через DistributedWorkerPool;
  3. Маршрутизацию к LocalGpuTransport (порт 11434 / RTX 5070 Ti);
  4. Замер времени отклика, пропускной способности (токенов/сек) и распределения нагрузки;
  5. Сбор телеметрии GPU и проверку инварианта fail-closed.

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R0.6 / Rassvet_AI_Fabric.
"""

from __future__ import annotations

__version__ = "1.0.0"

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

# Добавление src в sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from rai_fabric.distributed_pool import DistributedWorkerPool
from rai_fabric.fleet_common import write_cli_json_result
from rai_fabric.local_gpu_transport import LocalGpuTransport

logger = logging.getLogger("raif.stress_distributed_pool")


def run_stress_test(
    concurrency: int = 4,
    total_tasks: int = 20,
    worker_count: int = 3,
    prompt_prefix: str = "def solve_batch_item",
) -> Dict[str, Any]:
    """Выполнение сквозного стресс-теста пула воркеров."""
    transport = LocalGpuTransport(host="127.0.0.1", port=11434)
    pool = DistributedWorkerPool(gpu_transport=transport)

    # Регистрация воркеров
    for i in range(1, worker_count + 1):
        w_id = f"worker-gpu-{i:02d}"
        pool.register_worker(
            worker_id=w_id,
            capabilities=["inference", "code-eval", "batch-stream"],
            endpoint=f"local-loopback:{11434 + i}",
        )

    results: List[Dict[str, Any]] = []
    t_start = time.time()

    def _execute_task(idx: int) -> Dict[str, Any]:
        prompt = f"{prompt_prefix}_{idx}(data: list[int]) -> int:"
        task_id = f"stress-task-{idx:04d}"
        return pool.dispatch_inference_task(prompt=prompt, task_id=task_id, priority=1)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(_execute_task, i): i for i in range(1, total_tasks + 1)}
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)

    total_duration_ms = round((time.time() - t_start) * 1000.0, 2)
    successful = [r for r in results if r.get("status") == "COMPLETED"]
    total_tokens = sum(r.get("eval_count", 0) for r in successful)
    avg_latency_ms = round(sum(r.get("duration_ms", 0.0) for r in successful) / len(successful), 2) if successful else 0.0
    tokens_per_sec = round((total_tokens / (total_duration_ms / 1000.0)), 2) if total_duration_ms > 0 else 0.0

    gpu_telemetry = transport.query_gpu_telemetry()
    pool_status = pool.get_pool_status()

    report = {
        "status": "PASS" if len(successful) == total_tasks else "DEGRADED",
        "total_tasks": total_tasks,
        "completed_tasks": len(successful),
        "failed_tasks": total_tasks - len(successful),
        "concurrency": concurrency,
        "worker_count": worker_count,
        "total_duration_ms": total_duration_ms,
        "avg_latency_ms": avg_latency_ms,
        "total_tokens": total_tokens,
        "tokens_per_sec": tokens_per_sec,
        "gpu_telemetry": gpu_telemetry,
        "pool_distribution": {
            w["worker_id"]: {
                "completed": w["completed_tasks"],
                "active": w["active_tasks"],
            }
            for w in pool_status["workers"]
        },
    }
    return report


def main(args_list: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="DistributedWorkerPool E2E GPU Stress Benchmark")
    parser.add_argument("--tasks", type=int, default=20, help="Количество задач в пакете (по умолч.: 20)")
    parser.add_argument("--concurrency", type=int, default=4, help="Число параллельных потоков отправки")
    parser.add_argument("--workers", type=int, default=3, help="Количество зарегистрированных воркеров в пуле")
    parser.add_argument("--json", action="store_true", help="Вывод результатов в формате JSON")
    args = parser.parse_args(args_list)

    report = run_stress_test(
        concurrency=args.concurrency,
        total_tasks=args.tasks,
        worker_count=args.workers,
    )

    if args.json:
        write_cli_json_result(report)
    else:
        print("=== DistributedWorkerPool E2E Stress Report ===")
        print(f"Status:             {report['status']}")
        print(f"Tasks:              {report['completed_tasks']}/{report['total_tasks']} completed")
        print(f"Total Duration:     {report['total_duration_ms']} ms")
        print(f"Average Latency:    {report['avg_latency_ms']} ms")
        print(f"Total Tokens:       {report['total_tokens']}")
        print(f"Tokens/Sec:         {report['tokens_per_sec']} t/s")
        print(f"GPU:                {report['gpu_telemetry'].get('model', 'N/A')} ({report['gpu_telemetry'].get('vram_used_mb', 0)} MB used)")
        print(f"Distribution:       {json.dumps(report['pool_distribution'])}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
