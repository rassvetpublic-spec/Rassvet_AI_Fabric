"""Тесты для Stage R31: Аппаратный NVMe KV-кэш префиксов (src/rai_fabric/nvme_kv_cache.py)."""

import os
import shutil
import tempfile
from pathlib import Path
import pytest

from rai_fabric.nvme_kv_cache import NvmeKVCacheManager, HEADER_SIZE


@pytest.fixture
def temp_cache_dir():
    d = tempfile.mkdtemp(prefix="raif_test_nvme_cache_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def test_kv_cache_put_and_get_hit(temp_cache_dir):
    manager = NvmeKVCacheManager(temp_cache_dir, max_bytes=1024 * 1024, block_size=4096)
    model = "qwen2.5-coder:7b"
    prefix = "You are an expert AI assistant."
    payload = {"kv_tokens": [101, 2054, 2003], "vectors": [0.12, 0.45, -0.89]}

    assert manager.put(model, prefix, payload) is True
    res = manager.get(model, prefix)
    assert res == payload

    metrics = manager.get_metrics()
    assert metrics["hits"] == 1
    assert metrics["misses"] == 0
    assert metrics["hit_ratio_pct"] == 100.0
    assert metrics["entries_count"] == 1


def test_kv_cache_miss_and_isolation(temp_cache_dir):
    manager = NvmeKVCacheManager(temp_cache_dir, max_bytes=1024 * 1024, block_size=4096)
    res = manager.get("unknown_model", "prefix")
    assert res is None

    metrics = manager.get_metrics()
    assert metrics["misses"] == 1
    assert metrics["hits"] == 0


def test_zero_ssd_wear_page_alignment(temp_cache_dir):
    block_size = 4096
    manager = NvmeKVCacheManager(temp_cache_dir, max_bytes=1024 * 1024, block_size=block_size)
    manager.put("bge-m3", "Embedding prefix test", {"dim": 1024, "val": 1.0})

    files = list(temp_cache_dir.glob("*.raifcache"))
    assert len(files) == 1
    file_size = files[0].stat().st_size
    assert file_size % block_size == 0
    assert file_size >= block_size


def test_kv_cache_corruption_resilience(temp_cache_dir):
    manager = NvmeKVCacheManager(temp_cache_dir, max_bytes=1024 * 1024, block_size=4096)
    model = "deepseek-r1-distill"
    prefix = "System: analyze code"
    payload = {"result": "ok", "confidence": 0.99}

    manager.put(model, prefix, payload)
    files = list(temp_cache_dir.glob("*.raifcache"))
    assert len(files) == 1
    cache_file = files[0]

    # Искусственно портим 1 байт в области полезных данных (после заголовка)
    with open(cache_file, "r+b") as f:
        f.seek(HEADER_SIZE + 2)
        byte = f.read(1)
        flipped = bytes([byte[0] ^ 0xFF])
        f.seek(HEADER_SIZE + 2)
        f.write(flipped)

    # Fail-closed: чтение повреждённого блока должно вернуть None без исключения
    res = manager.get(model, prefix)
    assert res is None

    metrics = manager.get_metrics()
    assert metrics["corrupted_detected"] == 1
    # Повреждённый файл должен быть удалён
    assert not cache_file.exists()


def test_kv_cache_lru_eviction(temp_cache_dir):
    # Устанавливаем лимит ровно на 2 блока (4096 * 2 = 8192 байт)
    block_size = 4096
    manager = NvmeKVCacheManager(temp_cache_dir, max_bytes=block_size * 2, block_size=block_size)

    manager.put("m1", "p1", {"item": 1})
    manager.put("m2", "p2", {"item": 2})
    assert manager.get_metrics()["entries_count"] == 2

    # Добавляем 3-й элемент — должен вытесниться m1 (p1)
    manager.put("m3", "p3", {"item": 3})
    metrics = manager.get_metrics()
    assert metrics["evictions"] >= 1
    assert metrics["entries_count"] <= 2
    assert manager.get("m1", "p1") is None
    assert manager.get("m3", "p3") == {"item": 3}


def test_kv_cache_recovery_on_startup(temp_cache_dir):
    manager1 = NvmeKVCacheManager(temp_cache_dir, max_bytes=1024 * 1024, block_size=4096)
    manager1.put("m_rec", "p_rec", {"data": "persisted_value"})

    # Перезапуск менеджера (моделирование старта после рестарта службы)
    manager2 = NvmeKVCacheManager(temp_cache_dir, max_bytes=1024 * 1024, block_size=4096)
    assert manager2.get_metrics()["entries_count"] == 1
    res = manager2.get("m_rec", "p_rec")
    assert res == {"data": "persisted_value"}
