# -*- coding: utf-8 -*-
"""
tests.test_multi_model_daemon - Тесты многомодельного пула и эмбеддингов локального GPU (Stage R29 / Class A-X).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / Offline-Safe.
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

# Ensure scripts dir is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from importlib import import_module
daemon_module = import_module("local-gpu-daemon")
MultiModelPool = daemon_module.MultiModelPool
ModelSlot = daemon_module.ModelSlot
synthesize_embedding_response = daemon_module.synthesize_embedding_response
LocalGpuHttpHandler = daemon_module.LocalGpuHttpHandler


def test_model_slot_metadata():
    """Проверка корректной инициализации дескриптора ModelSlot."""
    slot = ModelSlot(
        name="test-model:7b",
        model_type="code",
        format_type="GGUF",
        quant="Q4_K_M",
        vram_mb=4000,
        description="Test coding model",
    )
    d = slot.to_dict()
    assert d["name"] == "test-model:7b"
    assert d["model_type"] == "code"
    assert d["vram_mb"] == 4000
    assert d["loaded"] is False


def test_multi_model_pool_budget_and_lru_eviction():
    """Проверка вытеснения по LRU при превышении лимита VRAM."""
    # Пул с бюджетом 10000 МБ
    pool = MultiModelPool(vram_budget_mb=10000)

    # Загружаем qwen2.5-coder:7b (5200 MB)
    ok, msg = pool.ensure_model_loaded("qwen2.5-coder:7b")
    assert ok is True
    assert pool.get_allocated_vram() >= 5200

    # Загружаем bge-m3 (1250 MB) -> суммарно 6450 MB < 10000 MB
    ok, msg = pool.ensure_model_loaded("bge-m3")
    assert ok is True
    assert pool.get_allocated_vram() == 5200 + 1250

    # Пытаемся загрузить qwen2.5-coder:7b-instruct-q5_k_m (6800 MB)
    # 6450 + 6800 = 13250 MB > 10000 MB -> LRU модель (qwen2.5-coder:7b) должна быть выгружена!
    time.sleep(0.01)
    # Отмечаем bge-m3 как недавно использованную
    pool.catalog["bge-m3"].last_used_ts = time.time() + 10.0

    ok, msg = pool.ensure_model_loaded("qwen2.5-coder:7b-instruct-q5_k_m")
    assert ok is True
    assert pool.catalog["qwen2.5-coder:7b-instruct-q5_k_m"].loaded is True
    # Проверяем, что суммарная аллокация не превысила бюджет 10000 MB
    assert pool.get_allocated_vram() <= 10000

    # Проверяем выгрузку
    ok, msg = pool.unload_model("qwen2.5-coder:7b-instruct-q5_k_m")
    assert ok is True
    assert pool.catalog["qwen2.5-coder:7b-instruct-q5_k_m"].loaded is False


def test_embedding_synthesis_determinism_and_norm():
    """Проверка генерации 1024-мерного нормализованного эмбеддинга."""
    text1 = "def verify_merkle_root(receipt): return True"
    text2 = "def verify_merkle_root(receipt): return True"
    text_diff = "something completely different for semantic test"

    resp1 = synthesize_embedding_response(text1, model="bge-m3")
    resp2 = synthesize_embedding_response(text2, model="bge-m3")
    resp_diff = synthesize_embedding_response(text_diff, model="bge-m3")

    assert resp1["model"] == "bge-m3"
    assert len(resp1["embedding"]) == 1024

    # Детерминизм: одинаковый текст даёт идентичный вектор
    assert resp1["embedding"] == resp2["embedding"]
    # Разный текст даёт отличающийся вектор
    assert resp1["embedding"] != resp_diff["embedding"]

    # Проверка L2-нормы вектора (должна быть 1.0 с точностью до округления)
    norm = math.sqrt(sum(x * x for x in resp1["embedding"]))
    assert pytest.approx(norm, rel=1e-3) == 1.0


def test_http_api_multi_model_and_embeddings():
    """Интеграционный тест HTTP-эндпоинтов /api/models, /api/embeddings, /api/telemetry."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalGpuHttpHandler)
    host, port = server.server_address
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://{host}:{port}"
    try:
        # 1. GET /api/models
        req = urllib.request.Request(f"{base_url}/api/models")
        with urllib.request.urlopen(req, timeout=3) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "catalog" in data
            assert "vram_budget_mb" in data
            assert data["vram_budget_mb"] > 0

        # 2. POST /api/models/load
        load_payload = json.dumps({"model": "bge-m3"}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/models/load",
            data=load_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "OK"

        # 3. POST /api/embeddings
        emb_payload = json.dumps({"model": "bge-m3", "prompt": "Rassvet AI Fabric Stage R29"}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/embeddings",
            data=emb_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "embedding" in data
            assert len(data["embedding"]) == 1024

        # 4. GET /api/telemetry
        req = urllib.request.Request(f"{base_url}/api/telemetry")
        with urllib.request.urlopen(req, timeout=3) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "telemetry" in data
            assert "model_pool" in data
            assert data["status"] == "ONLINE"

        # 5. GET /api/tags
        req = urllib.request.Request(f"{base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "models" in data
            model_names = [m["name"] for m in data["models"]]
            assert "qwen2.5-coder:7b" in model_names
            assert "bge-m3" in model_names

    finally:
        server.shutdown()
        server.server_close()
