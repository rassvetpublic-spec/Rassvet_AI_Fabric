# -*- coding: utf-8 -*-
"""
rai_fabric.model_replicator - Распределённая P2P-репликация тяжёлых моделей нейросетей по LAN (Stage R30 / R1.0).

Реализует:
  1. Content-addressed чанкование файлов моделей (GGUF, FP8) с формированием ModelManifest;
  2. In-memory SHA-256 валидацию каждого фрагмента без преждевременного износа SSD;
  3. Возобновляемую загрузку (Resumable Download) с отслеживанием прогресса по чанкам;
  4. Атомарную сборку модели и финальную сверку Merkle-корня (Root Hash);
  5. Соблюдение инварианта Safe Sync Gate (Fail-Closed, Zero SSD Wear).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R30 / Rassvet_AI_Fabric.
"""

from __future__ import annotations

__version__ = "1.0.0"

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rai_fabric.fleet_common import get_repo_root
from rai_fabric.tri_tower_sync import calculate_merkle_root

logger = logging.getLogger("raif.model_replicator")

DEFAULT_CHUNK_SIZE = 16 * 1024 * 1024  # 16 MB


class ModelManifest:
    """Манифест распределённой модели с метаданными и списком хэшей чанков."""

    def __init__(
        self,
        model_name: str,
        total_size_bytes: int,
        chunk_size_bytes: int,
        chunks_count: int,
        chunk_hashes: List[str],
        root_hash: str,
        format_type: str = "GGUF",
        quantization: str = "Q4_K_M",
    ) -> None:
        self.model_name = str(model_name)
        self.total_size_bytes = int(total_size_bytes)
        self.chunk_size_bytes = int(chunk_size_bytes)
        self.chunks_count = int(chunks_count)
        self.chunk_hashes = list(chunk_hashes)
        self.root_hash = str(root_hash)
        self.format_type = str(format_type)
        self.quantization = str(quantization)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol": "BPR5_NEXTGEN_R3.3",
            "stage": "STAGE_R30_MODEL_SYNC",
            "model_name": self.model_name,
            "format": self.format_type,
            "quantization": self.quantization,
            "total_size_bytes": self.total_size_bytes,
            "chunk_size_bytes": self.chunk_size_bytes,
            "chunks_count": self.chunks_count,
            "root_hash": self.root_hash,
            "chunk_hashes": self.chunk_hashes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ModelManifest:
        return cls(
            model_name=data.get("model_name", "unknown-model"),
            total_size_bytes=data.get("total_size_bytes", 0),
            chunk_size_bytes=data.get("chunk_size_bytes", DEFAULT_CHUNK_SIZE),
            chunks_count=data.get("chunks_count", 0),
            chunk_hashes=data.get("chunk_hashes", []),
            root_hash=data.get("root_hash", ""),
            format_type=data.get("format", "GGUF"),
            quantization=data.get("quantization", "Q4_K_M"),
        )

    @classmethod
    def create_from_file(
        cls,
        file_path: Path | str,
        model_name: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        format_type: str = "GGUF",
        quantization: str = "Q4_K_M",
    ) -> ModelManifest:
        """Создание манифеста модели из существующего локального файла."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Файл модели не найден: {path}")

        total_size = path.stat().st_size
        chunk_hashes: List[str] = []

        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h = hashlib.sha256(chunk).hexdigest()
                chunk_hashes.append(h)

        root_hash = calculate_merkle_root(chunk_hashes) if chunk_hashes else hashlib.sha256(b"").hexdigest()

        return cls(
            model_name=model_name,
            total_size_bytes=total_size,
            chunk_size_bytes=chunk_size,
            chunks_count=len(chunk_hashes),
            chunk_hashes=chunk_hashes,
            root_hash=root_hash,
            format_type=format_type,
            quantization=quantization,
        )


class ModelReplicator:
    """Менеджер экспорта, импорта и потоковой P2P-синхронизации файлов моделей."""

    def __init__(self, models_dir: Optional[Path | str] = None) -> None:
        if models_dir:
            self.models_dir = Path(models_dir)
        else:
            self.models_dir = get_repo_root() / ".models"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir = self.models_dir / ".staging"
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def _get_model_path(self, model_name: str) -> Path:
        safe_name = model_name.replace(":", "_").replace("/", "_")
        return self.models_dir / f"{safe_name}.bin"

    def _get_staging_chunk_path(self, model_name: str, chunk_index: int) -> Path:
        safe_name = model_name.replace(":", "_").replace("/", "_")
        return self.staging_dir / f"{safe_name}_chunk_{chunk_index:05d}.tmp"

    def export_chunk(
        self,
        model_name: str,
        chunk_index: int,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> Optional[bytes]:
        """Экспорт фрагмента модели для передачи запрашивающему пиру."""
        path = self._get_model_path(model_name)
        if not path.is_file():
            # Проверяем, есть ли чанк в staging
            staging_chunk = self._get_staging_chunk_path(model_name, chunk_index)
            if staging_chunk.is_file():
                return staging_chunk.read_bytes()
            return None

        offset = chunk_index * chunk_size
        total_size = path.stat().st_size
        if offset >= total_size:
            return None

        with open(path, "rb") as f:
            f.seek(offset)
            return f.read(chunk_size)

    def import_chunk(
        self,
        model_name: str,
        chunk_index: int,
        chunk_data: bytes,
        manifest: ModelManifest,
    ) -> bool:
        """
        Импорт и потоковая валидация фрагмента модели в RAM.
        При несовпадении хеша — отбрасывается без сохранения на диск (Fail-Closed).
        """
        if chunk_index < 0 or chunk_index >= manifest.chunks_count:
            logger.warning("Chunk index %d out of bounds (total: %d)", chunk_index, manifest.chunks_count)
            return False

        expected_hash = manifest.chunk_hashes[chunk_index]
        actual_hash = hashlib.sha256(chunk_data).hexdigest()

        if actual_hash != expected_hash:
            logger.error(
                "Chunk %d hash mismatch! Expected: %s, Actual: %s",
                chunk_index,
                expected_hash,
                actual_hash,
            )
            return False

        # Хэш проверен в RAM -> сохраняем во временный блок staging
        staging_path = self._get_staging_chunk_path(model_name, chunk_index)
        staging_path.write_bytes(chunk_data)
        return True

    def get_model_status(self, model_name: str, manifest: Optional[ModelManifest] = None) -> Dict[str, Any]:
        """Получение текущего статуса загрузки модели и процента завершённости."""
        model_path = self._get_model_path(model_name)
        if model_path.is_file():
            size = model_path.stat().st_size
            return {
                "model_name": model_name,
                "status": "COMPLETED",
                "progress_pct": 100.0,
                "file_path": str(model_path),
                "total_bytes": size,
            }

        if not manifest:
            return {
                "model_name": model_name,
                "status": "NOT_FOUND",
                "progress_pct": 0.0,
            }

        # Подсчёт присутствующих чанков в staging
        downloaded = 0
        missing_indices: List[int] = []
        for i in range(manifest.chunks_count):
            sp = self._get_staging_chunk_path(model_name, i)
            if sp.is_file():
                downloaded += 1
            else:
                missing_indices.append(i)

        pct = round((downloaded / max(manifest.chunks_count, 1)) * 100, 1)
        return {
            "model_name": model_name,
            "status": "IN_PROGRESS" if downloaded > 0 else "PENDING",
            "progress_pct": pct,
            "downloaded_chunks": downloaded,
            "total_chunks": manifest.chunks_count,
            "missing_indices": missing_indices,
            "root_hash": manifest.root_hash,
        }

    def finalize_model(self, model_name: str, manifest: ModelManifest) -> Tuple[bool, str]:
        """
        Атомарная сборка модели из проверенных чанков и итоговая верификация Merkle Root.
        """
        for i in range(manifest.chunks_count):
            sp = self._get_staging_chunk_path(model_name, i)
            if not sp.is_file():
                return False, f"Отсутствует чанк {i} из {manifest.chunks_count}"

        target_path = self._get_model_path(model_name)
        temp_target = target_path.with_suffix(".assembly.tmp")

        try:
            chunk_hashes: List[str] = []
            with open(temp_target, "wb") as out_f:
                for i in range(manifest.chunks_count):
                    sp = self._get_staging_chunk_path(model_name, i)
                    data = sp.read_bytes()
                    h = hashlib.sha256(data).hexdigest()
                    chunk_hashes.append(h)
                    out_f.write(data)

            # Проверка финального Merkle Root
            final_root = calculate_merkle_root(chunk_hashes)
            if final_root != manifest.root_hash:
                if temp_target.exists():
                    temp_target.unlink()
                return False, f"Финальный Merkle Root не совпал: {final_root} != {manifest.root_hash}"

            # Атомарная замена
            temp_target.replace(target_path)

            # Очистка staging
            for i in range(manifest.chunks_count):
                sp = self._get_staging_chunk_path(model_name, i)
                try:
                    sp.unlink()
                except OSError:
                    pass

            return True, f"Модель '{model_name}' успешно собрана и верифицирована (Размер: {target_path.stat().st_size} байт)"
        except Exception as exc:
            if temp_target.exists():
                temp_target.unlink()
            return False, f"Сбой финализации модели: {exc}"

    def replicate_from_peer(
        self,
        manifest: ModelManifest,
        peer_chunk_fetcher: Callable[[str, int], Optional[bytes]],
    ) -> Dict[str, Any]:
        """
        Сквозной процесс репликации недостающих чанков модели от удалённого пира.
        """
        t0 = time.perf_counter()
        status = self.get_model_status(manifest.model_name, manifest)
        if status["status"] == "COMPLETED":
            return {
                "status": "ALREADY_COMPLETED",
                "model_name": manifest.model_name,
                "chunks_replicated": 0,
                "elapsed_sec": 0.0,
            }

        missing = status.get("missing_indices", list(range(manifest.chunks_count)))
        replicated_count = 0
        failed_count = 0

        for idx in missing:
            chunk_bytes = peer_chunk_fetcher(manifest.model_name, idx)
            if not chunk_bytes:
                failed_count += 1
                continue
            ok = self.import_chunk(manifest.model_name, idx, chunk_bytes, manifest)
            if ok:
                replicated_count += 1
            else:
                failed_count += 1

        # Если все чанки успешно получены — собираем файл модели
        assembly_ok = False
        msg = ""
        if failed_count == 0 and (replicated_count + (manifest.chunks_count - len(missing))) == manifest.chunks_count:
            assembly_ok, msg = self.finalize_model(manifest.model_name, manifest)

        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "status": "SUCCESS" if assembly_ok else "PARTIAL",
            "model_name": manifest.model_name,
            "replicated_count": replicated_count,
            "failed_count": failed_count,
            "assembly_ok": assembly_ok,
            "message": msg,
            "elapsed_sec": elapsed,
        }
