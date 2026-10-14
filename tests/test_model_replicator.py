# -*- coding: utf-8 -*-
"""
tests.test_model_replicator - Тесты распределённого репликатора моделей по LAN (Stage R30 / Class C-Z).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / Offline-Safe.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from rai_fabric.model_replicator import ModelManifest, ModelReplicator


def test_manifest_creation_and_chunking(tmp_path):
    """Проверка генерации манифеста модели и корректного разбиения на чанки."""
    # Создаем синтетический файл модели размером 64 КБ (4 чанка по 16 КБ)
    model_file = tmp_path / "test_model_q4.bin"
    chunk_size = 16 * 1024
    payload = b"A" * (16 * 1024) + b"B" * (16 * 1024) + b"C" * (16 * 1024) + b"D" * (16 * 1024)
    model_file.write_bytes(payload)

    manifest = ModelManifest.create_from_file(
        file_path=model_file,
        model_name="qwen2.5-coder:7b",
        chunk_size=chunk_size,
    )

    assert manifest.model_name == "qwen2.5-coder:7b"
    assert manifest.total_size_bytes == 64 * 1024
    assert manifest.chunk_size_bytes == chunk_size
    assert manifest.chunks_count == 4
    assert len(manifest.chunk_hashes) == 4
    assert bool(manifest.root_hash)

    # Проверка круговой сериализации
    d = manifest.to_dict()
    restored = ModelManifest.from_dict(d)
    assert restored.model_name == manifest.model_name
    assert restored.root_hash == manifest.root_hash
    assert restored.chunk_hashes == manifest.chunk_hashes


def test_chunk_import_and_fail_closed_corruption(tmp_path):
    """Проверка отклонения поврежденных чанков (Fail-Closed, Zero SSD Wear)."""
    replicator = ModelReplicator(models_dir=tmp_path / "models")
    chunk_size = 1024
    data_chunk_0 = b"X" * chunk_size
    hash_0 = hashlib.sha256(data_chunk_0).hexdigest()

    manifest = ModelManifest(
        model_name="test-model:latest",
        total_size_bytes=chunk_size,
        chunk_size_bytes=chunk_size,
        chunks_count=1,
        chunk_hashes=[hash_0],
        root_hash=hash_0,
    )

    # 1. Попытка импортировать повреждённый чанк
    corrupted_data = b"Y" * chunk_size
    ok = replicator.import_chunk("test-model:latest", 0, corrupted_data, manifest)
    assert ok is False
    # Проверяем, что битый чанк не был сохранен
    staging_file = replicator._get_staging_chunk_path("test-model:latest", 0)
    assert not staging_file.exists()

    # 2. Импорт валидного чанка
    ok = replicator.import_chunk("test-model:latest", 0, data_chunk_0, manifest)
    assert ok is True
    assert staging_file.is_file()
    assert staging_file.read_bytes() == data_chunk_0


def test_model_assembly_and_root_integrity(tmp_path):
    """Проверка атомарной сборки файла модели и сверки Merkle Root."""
    replicator = ModelReplicator(models_dir=tmp_path / "models")
    chunk_size = 1024
    c0 = b"1" * chunk_size
    c1 = b"2" * chunk_size
    h0 = hashlib.sha256(c0).hexdigest()
    h1 = hashlib.sha256(c1).hexdigest()

    from rai_fabric.tri_tower_sync import calculate_merkle_root
    root = calculate_merkle_root([h0, h1])

    manifest = ModelManifest(
        model_name="assembled-model",
        total_size_bytes=chunk_size * 2,
        chunk_size_bytes=chunk_size,
        chunks_count=2,
        chunk_hashes=[h0, h1],
        root_hash=root,
    )

    assert replicator.import_chunk("assembled-model", 0, c0, manifest) is True
    assert replicator.import_chunk("assembled-model", 1, c1, manifest) is True

    ok, msg = replicator.finalize_model("assembled-model", manifest)
    assert ok is True

    target_path = replicator._get_model_path("assembled-model")
    assert target_path.is_file()
    assert target_path.read_bytes() == c0 + c1

    # Проверка статуса завершённости
    status = replicator.get_model_status("assembled-model", manifest)
    assert status["status"] == "COMPLETED"
    assert status["progress_pct"] == 100.0


def test_peer_replication_flow(tmp_path):
    """Сквозная P2P-репликация модели между донором и реципиентом."""
    donor_dir = tmp_path / "donor_models"
    recipient_dir = tmp_path / "recipient_models"

    donor = ModelReplicator(models_dir=donor_dir)
    recipient = ModelReplicator(models_dir=recipient_dir)

    # Донор создаёт модель 32 КБ
    model_name = "bge-m3:fp8"
    donor_file = donor._get_model_path(model_name)
    sample_content = os.urandom(32 * 1024)
    donor_file.write_bytes(sample_content)

    manifest = ModelManifest.create_from_file(
        file_path=donor_file,
        model_name=model_name,
        chunk_size=8 * 1024,
    )
    assert manifest.chunks_count == 4

    # Функция-шлюз получения чанков от донора
    def fetch_from_donor(m_name: str, c_idx: int):
        return donor.export_chunk(m_name, c_idx, chunk_size=manifest.chunk_size_bytes)

    # Репликация на реципиенте
    result = recipient.replicate_from_peer(manifest, peer_chunk_fetcher=fetch_from_donor)
    assert result["status"] == "SUCCESS"
    assert result["replicated_count"] == 4
    assert result["assembly_ok"] is True

    # Проверка полной байтовой идентичности
    recipient_file = recipient._get_model_path(model_name)
    assert recipient_file.is_file()
    assert recipient_file.read_bytes() == sample_content
