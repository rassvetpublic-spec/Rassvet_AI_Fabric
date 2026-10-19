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
import math
import os
import time
import zlib
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, Iterator, List, Optional, Tuple

from rai_fabric.fleet_common import get_repo_root
from rai_fabric.tri_tower_sync import calculate_merkle_root

logger = logging.getLogger("raif.model_replicator")

DEFAULT_CHUNK_SIZE = 16 * 1024 * 1024  # 16 MB

# 256 детерминированных 32-битных коэффициентов Gear для FastCDC
GEAR_MATRIX = [
    0x5BE0CD19, 0x1F15CD51, 0x0A52DE09, 0xA8E571F1, 0x69680509, 0x76A03507, 0x4D368FD7, 0x6E565257,
    0x5672FA47, 0xF972E9D1, 0x67C2F009, 0x4CE7C7AF, 0x86AC5E29, 0x5824C6EE, 0x55EEB581, 0x05483B5E,
    0x77741F71, 0x2A1BE8E7, 0x3F676B23, 0xF47551B5, 0x7CA428C1, 0x82693BE5, 0x438641EB, 0x1AEB4527,
    0x386CEEC5, 0x44BE7F69, 0x7B1E4E71, 0x86B2F7E7, 0xA9966D41, 0x1E462F47, 0x2A62C64B, 0x32AE1E19,
    0x7ACD9F61, 0x3DB2A577, 0x5EE33441, 0x125191A7, 0x64426BE5, 0x6F4932F1, 0x0EDF337B, 0x8DF12A13,
    0x615F4957, 0x8D218335, 0x5393CE9B, 0x27C9F757, 0x7433B761, 0x3AA38A53, 0x153A0429, 0x5B5F348F,
    0x2EAF7191, 0x7508496B, 0x175DF4C9, 0x4D79590B, 0x16346297, 0x6B19B267, 0x8B3B59D1, 0x26AC8445,
    0x3A21BD77, 0x234F3679, 0x58A3CE11, 0x24B3EB89, 0x30138C47, 0x47781C55, 0x1812E27B, 0x309C5A87,
    0x4E747F95, 0x2897593B, 0x4F04A7B7, 0x6AE32711, 0x2B7A8129, 0x7F26E6F5, 0x6A6B8081, 0x78531777,
    0x6F61314B, 0x33445C11, 0x618525E7, 0x3C49B2F5, 0x3C9A6197, 0x709C6F61, 0x46450A9B, 0x26685819,
    0x2035F147, 0x75218D19, 0x5776C559, 0x7F27CE2B, 0x1D3B5145, 0x11311C27, 0x3841D6B7, 0x217277E5,
    0x629C2337, 0x117E3F29, 0x155452D1, 0x3A75B495, 0x2A1521B5, 0x7B9A458B, 0x717013C9, 0x2B49CD39,
    0x13380B51, 0x2117A167, 0x78860B95, 0x414597F5, 0x323497F5, 0x468817D5, 0x45486C11, 0x5821F453,
    0x498177F7, 0x4E8E2D17, 0x53528A4B, 0x50186989, 0x3D11F9E9, 0x581373A5, 0x1E59C759, 0x1E2B889B,
    0x40366D67, 0x738A5A69, 0x40134F47, 0x12711C45, 0x103E793B, 0x6A192667, 0x376E6A21, 0x4E2B1A3B,
    0x2324F973, 0x5F1965A1, 0x5D524F57, 0x37351651, 0x729C1F17, 0x28892695, 0x5C89C7D5, 0x7621CD55,
    0x30691517, 0x62153B8B, 0x553597D5, 0x36480B67, 0x6424D515, 0x5C86C1D9, 0x4778E295, 0x76879B59,
    0x35574519, 0x64692745, 0x4657B451, 0x712B3B15, 0x4C542B11, 0x38914619, 0x756B7D57, 0x3732E967,
    0x673966F9, 0x2213F985, 0x1D237A47, 0x3554CD7B, 0x4D368A6B, 0x6B198425, 0x6629B7F1, 0x4B364955,
    0x544E8C2B, 0x2A15CD59, 0x2E687799, 0x75932821, 0x2479244B, 0x545B8E67, 0x4774B399, 0x145B11B9,
    0x7F265D3B, 0x4858B4A5, 0x7654C47B, 0x67623945, 0x355799F1, 0x7F411C2B, 0x54366A49, 0x2874CD35,
    0x256B44F1, 0x3E5466F9, 0x35198C45, 0x288768A5, 0x6618F957, 0x599C44F1, 0x446B89F5, 0x5A737F99,
    0x7426E927, 0x6A3297A5, 0x2649B229, 0x582B1489, 0x6968B4C5, 0x43867A55, 0x5C396B7B, 0x1276C759,
    0x754F8E29, 0x5672CD59, 0x67542F19, 0x1654C4F5, 0x66868E49, 0x77765171, 0x46429A2B, 0x7665793B,
    0x6E562F41, 0x45238B57, 0x48967A45, 0x5A88B351, 0x74868F45, 0x5776CD79, 0x2323B519, 0x755F6A47,
    0x386C5A21, 0x7E35E981, 0x794966B5, 0x464B7D25, 0x6C729A39, 0x5D54C115, 0x254F2719, 0x1872CD55,
    0x7A748677, 0x668615A1, 0x4A86C72B, 0x2A19F7E5, 0x50186989, 0x3A2197A5, 0x468817D5, 0x77741F71,
    0x6424D515, 0x4D79590B, 0x7B1E4E71, 0x2EAF7191, 0x1F15CD51, 0x5BE0CD19, 0x76A03507, 0x69680509,
    0x6E565257, 0x4D368FD7, 0xF972E9D1, 0x5672FA47, 0x4CE7C7AF, 0x67C2F009, 0x5824C6EE, 0x86AC5E29,
    0x05483B5E, 0x55EEB581, 0x2A1BE8E7, 0x77741F71, 0xF47551B5, 0x3F676B23, 0x82693BE5, 0x7CA428C1,
    0x1AEB4527, 0x438641EB, 0x44BE7F69, 0x386CEEC5, 0x86B2F7E7, 0x7B1E4E71, 0x1E462F47, 0xA9966D41,
    0x32AE1E19, 0x2A62C64B, 0x3DB2A577, 0x7ACD9F61, 0x125191A7, 0x5EE33441, 0x6F4932F1, 0x64426BE5,
]


class FastCDCChunker:
    """Контентно-определённое чанкование (Content-Defined Chunking) с Gear Hash (Stage R33 / R4)."""

    def __init__(
        self,
        min_size: int = 4 * 1024 * 1024,
        avg_size: int = 16 * 1024 * 1024,
        max_size: int = 32 * 1024 * 1024,
    ) -> None:
        self.min_size = min_size
        self.avg_size = avg_size
        self.max_size = max_size
        bits = max(1, int(math.log2(avg_size))) if avg_size > 1 else 1
        self.mask = (1 << bits) - 1

    def chunk_stream(
        self,
        data_stream: BinaryIO,
        min_size: Optional[int] = None,
        avg_size: Optional[int] = None,
        max_size: Optional[int] = None,
    ) -> Iterator[Tuple[bytes, str]]:
        """Разбиение входного потока на переменные блоки FastCDC с вычислением SHA-256."""
        c_min = min_size if min_size is not None else self.min_size
        c_avg = avg_size if avg_size is not None else self.avg_size
        c_max = max_size if max_size is not None else self.max_size
        bits = max(1, int(math.log2(c_avg))) if c_avg > 1 else 1
        mask = (1 << bits) - 1

        buf = bytearray()
        gear_hash = 0

        while True:
            read_bytes = data_stream.read(64 * 1024)
            if not read_bytes:
                if buf:
                    chunk = bytes(buf)
                    yield chunk, hashlib.sha256(chunk).hexdigest()
                break

            for b in read_bytes:
                buf.append(b)
                gear_hash = (((gear_hash << 1) & 0xFFFFFFFF) + GEAR_MATRIX[b]) & 0xFFFFFFFF

                if len(buf) >= c_min:
                    if len(buf) >= c_max or (gear_hash & mask) == 0:
                        chunk = bytes(buf)
                        yield chunk, hashlib.sha256(chunk).hexdigest()
                        buf.clear()
                        gear_hash = 0


class ZstdCompressorWrapper:
    """Потоковое сжатие чанков моделей с адаптивным fallback (Zstandard / zlib)."""

    def __init__(self, level: int = 3) -> None:
        self.level = level
        self._has_zstd = False
        try:
            import zstandard as zstd
            self._zstd = zstd
            self._has_zstd = True
        except ImportError:
            self._zstd = None

    def compress_chunk(self, chunk: bytes, level: Optional[int] = None) -> bytes:
        lvl = level if level is not None else self.level
        if self._has_zstd and self._zstd:
            cctx = self._zstd.ZstdCompressor(level=lvl)
            return b"ZSTD" + cctx.compress(chunk)
        return b"ZLIB" + zlib.compress(chunk, level=min(9, max(1, lvl)))

    def decompress_chunk(self, compressed_chunk: bytes) -> bytes:
        if compressed_chunk.startswith(b"ZSTD") and self._has_zstd and self._zstd:
            dctx = self._zstd.ZstdDecompressor()
            return dctx.decompress(compressed_chunk[4:])
        if compressed_chunk.startswith(b"ZLIB"):
            return zlib.decompress(compressed_chunk[4:])
        try:
            return zlib.decompress(compressed_chunk)
        except Exception:
            return compressed_chunk


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
        # Metadata-bound in-process proof cache; no additional runtime files.
        self._verified_model_cache: Dict[str, Tuple[str, int, int, int]] = {}

    def _matches_manifest(self, path: Path, manifest: ModelManifest) -> bool:
        """Verify an existing model in bounded RAM; never trust file presence alone."""
        size = manifest.total_size_bytes
        chunk_size = manifest.chunk_size_bytes
        if (size <= 0 or chunk_size <= 0 or manifest.chunks_count != len(manifest.chunk_hashes)
                or manifest.chunks_count != (size + chunk_size - 1) // chunk_size):
            return False
        try:
            before = path.stat()
            if before.st_size != size:
                return False
            stamp = (manifest.root_hash, before.st_size, before.st_mtime_ns, before.st_ino)
            if self._verified_model_cache.get(str(path)) == stamp:
                return True
            hashes: List[str] = []
            with path.open("rb") as source:
                for index, expected in enumerate(manifest.chunk_hashes):
                    remaining = min(chunk_size, size - index * chunk_size)
                    digest = hashlib.sha256()
                    while remaining:
                        block = source.read(min(1024 * 1024, remaining))
                        if not block:
                            return False
                        digest.update(block)
                        remaining -= len(block)
                    actual = digest.hexdigest()
                    if actual != expected:
                        return False
                    hashes.append(actual)
                if source.read(1):
                    return False
            after = path.stat()
            if ((before.st_size, before.st_mtime_ns, before.st_ino) !=
                    (after.st_size, after.st_mtime_ns, after.st_ino)):
                return False
            if calculate_merkle_root(hashes) != manifest.root_hash:
                return False
            self._verified_model_cache[str(path)] = stamp
            return True
        except OSError:
            return False

    def _get_model_path(self, model_name: str) -> Path:
        safe_name = model_name.replace("\\", "_").replace(":", "_").replace("/", "_")
        return self.models_dir / f"{safe_name}.bin"

    def _get_staging_chunk_path(self, model_name: str, chunk_index: int) -> Path:
        safe_name = model_name.replace("\\", "_").replace(":", "_").replace("/", "_")
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

    def import_chunk_direct(
        self,
        model_name: str,
        chunk_index: int,
        offset: int,
        chunk_data: bytes,
        expected_hash: str,
        total_size: Optional[int] = None,
    ) -> bool:
        """
        Прямая запись чанка по смещению в итоговый файл модели без staging (Zero SSD Wear / R4).
        Проверяет SHA-256 в RAM перед выполнением seek + write.
        """
        # An untrusted peer's chunk index/offset must never cause out-of-bounds
        # sparse-file writes or overwrite bytes beyond a supplied manifest size.
        if (not isinstance(chunk_index, int) or chunk_index < 0 or
                not isinstance(offset, int) or offset < 0 or
                (total_size is not None and
                 (not isinstance(total_size, int) or total_size < 0 or
                  offset > total_size or len(chunk_data) > total_size - offset))):
            return False
        actual_hash = hashlib.sha256(chunk_data).hexdigest()
        if actual_hash != expected_hash:
            logger.error(
                "Direct chunk %d hash mismatch! Expected: %s, got: %s",
                chunk_index,
                expected_hash,
                actual_hash,
            )
            return False

        target_path = self._get_model_path(model_name)
        mode = "r+b" if target_path.exists() else "wb"
        with open(target_path, mode) as f:
            f.seek(offset)
            f.write(chunk_data)
            f.flush()
        self._verified_model_cache.pop(str(target_path), None)
        return True

    def get_model_status(self, model_name: str, manifest: Optional[ModelManifest] = None) -> Dict[str, Any]:
        """Получение текущего статуса загрузки модели и процента завершённости."""
        model_path = self._get_model_path(model_name)
        model_present = model_path.is_file()
        if model_present:
            size = model_path.stat().st_size
            if manifest is None:
                return {
                    "model_name": model_name, "status": "PRESENT_UNVERIFIED",
                    "progress_pct": 0.0, "file_path": str(model_path), "total_bytes": size,
                }
            if self._matches_manifest(model_path, manifest):
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
            "status": ("CORRUPTED" if model_present else
                       ("IN_PROGRESS" if downloaded > 0 else "PENDING")),
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

            # Never attest a complete model if its payload size differs from the manifest.
            if temp_target.stat().st_size != manifest.total_size_bytes:
                temp_target.unlink()
                return False, "Размер собранной модели не соответствует манифесту"
            # Проверка финального Merkle Root
            final_root = calculate_merkle_root(chunk_hashes)
            if final_root != manifest.root_hash:
                if temp_target.exists():
                    temp_target.unlink()
                return False, f"Финальный Merkle Root не совпал: {final_root} != {manifest.root_hash}"

            # Атомарная замена
            temp_target.replace(target_path)
            verified_stat = target_path.stat()
            self._verified_model_cache[str(target_path)] = (
                manifest.root_hash, verified_stat.st_size,
                verified_stat.st_mtime_ns, verified_stat.st_ino,
            )

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
