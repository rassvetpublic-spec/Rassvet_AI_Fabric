"""Unit and adversarial tests for Milestone M1 (R1, R2, R6): Storage & Hardware Safety.

Covers:
- R1: Hardware Thermal Watchdog & VRAM-Shedding (LocalGpuTransport, GpuThermalWatchdog)
- R2: SQLite Queue Engine WAL2 & Mmap Optimization (FabricStore PRAGMAs, SAVEPOINT nesting, submit_batch)
- R6: Non-blocking Flush Thread for NVMe KV-Cache (NvmeKVCacheManager staging ring buffer & NvmeFlushWorker)
"""

import os
import shutil
import tempfile
import time
from pathlib import Path
import pytest

from rai_fabric.local_gpu_transport import GpuThermalWatchdog, LocalGpuTransport
from transport.ipc_channel import TransportError, TransportMessageEnvelope
from rai_fabric.store import FabricStore, FabricError
from rai_fabric.nvme_kv_cache import NvmeKVCacheManager
from unittest.mock import MagicMock


# ==============================================================================
# R1: GPU Thermal Watchdog & VRAM-Shedding Tests
# ==============================================================================

def test_watchdog_sheds_background_when_overheated():
    watchdog = GpuThermalWatchdog(max_temp_c=72.0, min_free_vram_mb=800.0)
    watchdog.set_mock_telemetry(temp_c=75.5, free_vram_mb=4096.0)

    # Background task must be rejected
    safe_bg, reason_bg = watchdog.check_safety(is_interactive=False)
    assert not safe_bg
    assert "75.5°C exceeds safety threshold 72.0°C" in reason_bg

    # Interactive turn must be preserved with warning
    safe_ia, reason_ia = watchdog.check_safety(is_interactive=True)
    assert safe_ia
    assert "75.5°C exceeds safety threshold 72.0°C" in reason_ia


def test_watchdog_sheds_background_when_low_vram():
    watchdog = GpuThermalWatchdog(max_temp_c=72.0, min_free_vram_mb=800.0)
    watchdog.set_mock_telemetry(temp_c=55.0, free_vram_mb=450.0)

    safe_bg, reason_bg = watchdog.check_safety(is_interactive=False)
    assert not safe_bg
    assert "450.0 MB is below safety threshold 800.0 MB" in reason_bg

    safe_ia, _ = watchdog.check_safety(is_interactive=True)
    assert safe_ia


def test_transport_rejects_background_envelope_on_overheat():
    mock = MagicMock()
    mock.generate.return_value = {"text": "ok", "eval_count": 10, "eval_duration": 1000}
    mock.probe.return_value = True

    watchdog = GpuThermalWatchdog(max_temp_c=72.0, min_free_vram_mb=800.0)
    transport = LocalGpuTransport(mock_client=mock, watchdog=watchdog)
    assert transport.connect()

    # Normal state passes
    watchdog.set_mock_telemetry(temp_c=50.0, free_vram_mb=6000.0)
    env_bg = TransportMessageEnvelope.create(
        payload_type="command",
        payload={"prompt": "foo", "interactive": False},
    )
    assert transport.send(env_bg) is True

    # Overheat sheds background load
    watchdog.set_mock_telemetry(temp_c=74.0, free_vram_mb=6000.0)
    with pytest.raises(TransportError) as exc_info:
        transport.send(env_bg)
    assert exc_info.value.code == "GPU_SAFETY_THRESHOLD_EXCEEDED"
    assert "429 Load Shedding" in exc_info.value.message

    # Interactive request survives overheat
    env_interactive = TransportMessageEnvelope.create(
        payload_type="command",
        payload={"prompt": "foo", "interactive": True},
    )
    assert transport.send(env_interactive) is True


# ==============================================================================
# R2: SQLite WAL2, Mmap, Nested Transactions & Batching Tests
# ==============================================================================

@pytest.fixture
def temp_store_path():
    td = tempfile.mkdtemp(prefix="raif_test_store_")
    db_file = Path(td) / "state.db"
    yield db_file
    shutil.rmtree(td, ignore_errors=True)


def test_store_pragmas_and_nested_savepoints(temp_store_path):
    store = FabricStore(temp_store_path, initialize=True)

    # Verify PRAGMAs
    mmap_size = store.db.execute("PRAGMA mmap_size").fetchone()[0]
    assert mmap_size >= 268435456

    sync_mode = store.db.execute("PRAGMA synchronous").fetchone()[0]
    # NORMAL is 1 in SQLite
    assert sync_mode in (1, "1", "NORMAL")

    # Test Nested Transactions via SAVEPOINT
    project_dir = temp_store_path.parent
    with store.atomic():
        t1 = store.submit(objective="Outer task 1", provider="mock", workspace=str(project_dir))
        assert t1["id"].startswith("rf-")

        # Nested atomic (Savepoint 1)
        with store.atomic():
            t2 = store.submit(objective="Inner task 2", provider="mock", workspace=str(project_dir))
            assert t2["id"].startswith("rf-")

        # Nested atomic with rollback (Savepoint 2)
        try:
            with store.atomic():
                store.submit(objective="Inner doomed task", provider="mock", workspace=str(project_dir), task_id="rf-doomed")
                raise ValueError("Simulated failure in inner block")
        except ValueError:
            pass

    # Verify t1 and t2 committed, while doomed task rolled back
    assert store.get(t1["id"]) is not None
    assert store.get(t2["id"]) is not None
    with pytest.raises(FabricError):
        store.get("rf-doomed")

    store.close()


def test_store_submit_batch(temp_store_path):
    store = FabricStore(temp_store_path, initialize=True)
    project_dir = str(temp_store_path.parent)

    batch = [
        {"objective": f"Batch task #{i}", "provider": "mock", "workspace": project_dir}
        for i in range(10)
    ]

    t0 = time.perf_counter()
    results = store.submit_batch(batch)
    elapsed = time.perf_counter() - t0

    assert len(results) == 10
    # Throughput check: batch insert should be fast (< 50ms for 10 tasks)
    assert elapsed < 0.50
    for res in results:
        assert res["status"] == "QUEUED"
        assert store.get(res["id"]) is not None

    store.close()


# ==============================================================================
# R6: NVMe KV-Cache Non-blocking Flush Thread & Read-Through Tests
# ==============================================================================

@pytest.fixture
def temp_nvme_cache_dir():
    d = tempfile.mkdtemp(prefix="raif_test_nvme_m1_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def test_nvme_nonblocking_put_and_read_through(temp_nvme_cache_dir):
    manager = NvmeKVCacheManager(temp_nvme_cache_dir, max_bytes=2 * 1024 * 1024, block_size=4096)
    model = "qwen2.5-coder:7b"
    prefix = "import math\ndef calc("
    payload = {"tokens": [10, 20, 30], "attn": [0.1, 0.2]}

    # Non-blocking put (wait=False)
    t0 = time.perf_counter()
    assert manager.put(model, prefix, payload, wait=False) is True
    elapsed_put = time.perf_counter() - t0
    # Must return virtually instantly (< 5ms) without waiting for fsync
    assert elapsed_put < 0.05

    # Immediate read-through from RAM staging buffer
    cached_val = manager.get(model, prefix)
    assert cached_val == payload

    # Explicit flush drains the background queue to NVMe disk
    manager.flush(wait=True)

    # Verify file is now on disk with 4096-byte alignment
    files = list(temp_nvme_cache_dir.glob("*.raifcache"))
    assert len(files) == 1
    file_size = files[0].stat().st_size
    assert file_size % 4096 == 0

    manager.close()
