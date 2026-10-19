"""rai_fabric.nvme_kv_cache - Аппаратный KV-кэш префиксов на NVMe с защитой от износа SSD (Stage R31).

Предоставляет кольцевое и блочно-выровненное кэширование префиксов промптов и эмбеддингов
для быстрой ротации моделей в MultiModelPool без избыточных циклов перезаписи SSD.
"""

from __future__ import annotations

__version__ = "1.0.0"

import hashlib
import json
import os
import queue
import struct
import threading
import time
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAGIC_HEADER = b"RAIF"
FORMAT_VERSION = 1
# Header format: 4s (magic) + H (version) + 32s (key_sha256) + I (data_len) + I (crc32) + d (timestamp)
HEADER_STRUCT = struct.Struct("<4sH32sIId")
HEADER_SIZE = HEADER_STRUCT.size


class NvmeKVCacheEntry:
    """Запись кэша префикса."""

    def __init__(
        self,
        key: str,
        model_id: str,
        payload_bytes: bytes,
        checksum: int,
        timestamp: float,
        file_path: Path,
    ) -> None:
        self.key = key
        self.model_id = model_id
        self.payload_bytes = payload_bytes
        self.checksum = checksum
        self.timestamp = timestamp
        self.file_path = file_path
        self.access_count = 1
        self.last_accessed = timestamp


class NvmeKVCacheManager:
    """Менеджер блочного NVMe KV-кэша с защитой Zero SSD Wear."""

    def __init__(
        self,
        cache_dir: Path | str,
        max_bytes: int = 64 * 1024 * 1024,
        block_size: int = 4096,
    ) -> None:
        if (type(max_bytes) is not int or max_bytes <= 0 or
                type(block_size) is not int or block_size <= 0):
            raise ValueError("Cache limits must be positive integers")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.block_size = block_size

        self._index: Dict[str, NvmeKVCacheEntry] = {}
        self._current_bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._corrupted_count = 0

        self._lock = threading.Lock()
        self._staging_dict: Dict[str, Any] = {}
        self._staging_queue: queue.Queue[Optional[Tuple[str, str, Any]]] = queue.Queue(maxsize=4096)
        self._worker_running = True
        self._flush_thread = threading.Thread(target=self._worker_loop, daemon=True, name="NvmeFlushWorker")
        self._flush_thread.start()

        self._scan_and_recover()

    def _worker_loop(self) -> None:
        """Фоновый рабочий поток сброса отложенных записей на NVMe (R6)."""
        # Drain queued writes before the sentinel. Every dequeue must ack, even
        # when the disk write raises: otherwise flush()/close() can hang forever.
        while True:
            try:
                item = self._staging_queue.get(timeout=0.1)
            except queue.Empty:
                if not self._worker_running:
                    break
                continue
            try:
                if item is None:
                    break
                model_id, prompt_prefix, payload = item
                key = self.compute_key(model_id, prompt_prefix)
                try:
                    with self._lock:
                        self._write_entry(model_id, prompt_prefix, payload)
                finally:
                    with self._lock:
                        if self._staging_dict.get(key) is payload:
                            self._staging_dict.pop(key, None)
            except Exception:
                # The failed write is a cache miss, never a durable cache hit.
                pass
            finally:
                self._staging_queue.task_done()

    @staticmethod
    def compute_key(model_id: str, prompt_prefix: str) -> str:
        """Детерминированный ключ записи: sha256(model_id + '::' + prompt_prefix)."""
        raw = f"{model_id.strip()}::{prompt_prefix.strip()}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _entry_size(self, entry: NvmeKVCacheEntry) -> int:
        n = HEADER_SIZE + len(entry.payload_bytes)
        return ((n + self.block_size - 1) // self.block_size) * self.block_size

    def _pad_to_block_size(self, data: bytes) -> bytes:
        """Выравнивание блока по размеру страницы (Zero SSD Wear alignment)."""
        rem = len(data) % self.block_size
        if rem == 0:
            return data
        padding = self.block_size - rem
        return data + (b"\x00" * padding)

    def _write_entry(self, model_id: str, prompt_prefix: str, payload: Any) -> bool:
        """Синхронная запись блока на диск с 4096-выравниванием."""
        key = self.compute_key(model_id, prompt_prefix)
        key_bytes = bytes.fromhex(key)

        if isinstance(payload, bytes):
            serialized = payload
        else:
            serialized = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        data_len = len(serialized)
        crc = zlib.crc32(serialized) & 0xFFFFFFFF
        ts = time.time()

        header = HEADER_STRUCT.pack(MAGIC_HEADER, FORMAT_VERSION, key_bytes, data_len, crc, ts)
        raw_block = header + serialized
        aligned_block = self._pad_to_block_size(raw_block)

        block_total_len = len(aligned_block)
        if block_total_len > self.max_bytes:
            return False

        target_file = self.cache_dir / f"{key}.raifcache"
        tmp_file = self.cache_dir / f"{key}.tmp"
        if target_file.is_symlink() or tmp_file.is_symlink():
            return False
        old_size = 0
        if key in self._index and target_file.is_file():
            old_size = target_file.stat().st_size

        created_temp = False
        try:
            # O_EXCL prevents accidentally truncating a preexisting or
            # symlinked temporary file with this predictable SHA-derived name.
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            fd = os.open(tmp_file, flags, 0o600)
            created_temp = True
            with os.fdopen(fd, "wb") as f:
                f.write(aligned_block)
                f.flush()
                os.fsync(f.fileno())
            # Replacement should reserve only the *delta* in effective usage.
            if not self._ensure_capacity(max(0, block_total_len - old_size), protected_key=key):
                return False
            tmp_file.replace(target_file)
        except OSError:
            return False
        finally:
            if created_temp and tmp_file.exists():
                try:
                    tmp_file.unlink(missing_ok=True)
                except OSError:
                    pass

        entry = NvmeKVCacheEntry(
            key=key,
            model_id=model_id,
            payload_bytes=serialized,
            checksum=crc,
            timestamp=ts,
            file_path=target_file,
        )

        if key in self._index:
            self._current_bytes = max(0, self._current_bytes - old_size)

        self._index[key] = entry
        self._current_bytes += block_total_len
        return True

    def put(
        self,
        model_id: str,
        prompt_prefix: str,
        payload: Any,
        wait: bool = True,
    ) -> bool:
        """Сохранение полезной нагрузки префикса в блочный кэш.
        
        Если wait=False, запись асинхронно ставится в очередь фонового потока (Milestone M1 / R6).
        """
        if wait:
            with self._lock:
                return self._write_entry(model_id, prompt_prefix, payload)
        else:
            key = self.compute_key(model_id, prompt_prefix)
            with self._lock:
                if not self._worker_running:
                    return False
                try:
                    self._staging_queue.put_nowait((model_id, prompt_prefix, payload))
                except queue.Full:
                    return False
                # Staging becomes visible only after enqueue succeeds.
                self._staging_dict[key] = payload
            return True

    def get(
        self,
        model_id: str,
        prompt_prefix: str,
    ) -> Optional[Any]:
        """Извлечение префикса из кэша с проверкой CRC32 (Fail-closed) и read-through staging."""
        key = self.compute_key(model_id, prompt_prefix)
        with self._lock:
            if key in self._staging_dict:
                self._hits += 1
                return self._staging_dict[key]

            if key not in self._index:
                self._misses += 1
                return None

            entry = self._index[key]
            if entry.file_path.is_symlink() or not entry.file_path.exists():
                self._misses += 1
                self._current_bytes = max(0, self._current_bytes - self._entry_size(entry))
                del self._index[key]
                return None

        try:
            with open(entry.file_path, "rb") as f:
                raw_header = f.read(HEADER_SIZE)
                if len(raw_header) < HEADER_SIZE:
                    raise ValueError("Truncated header")
                magic, ver, k_bytes, d_len, stored_crc, ts = HEADER_STRUCT.unpack(raw_header)

                if magic != MAGIC_HEADER or ver != FORMAT_VERSION:
                    raise ValueError("Magic/version mismatch")

                if k_bytes != bytes.fromhex(key):
                    raise ValueError("Key mismatch")
                file_size = os.fstat(f.fileno()).st_size
                if (d_len > file_size - HEADER_SIZE or
                        d_len > self.max_bytes - HEADER_SIZE):
                    raise ValueError("Payload length exceeds cache/file budget")

                payload_bytes = f.read(d_len)
                if len(payload_bytes) < d_len:
                    raise ValueError("Truncated payload")

                computed_crc = zlib.crc32(payload_bytes) & 0xFFFFFFFF
                if computed_crc != stored_crc:
                    raise ValueError(f"CRC mismatch: {computed_crc} != {stored_crc}")

            with self._lock:
                entry.access_count += 1
                entry.last_accessed = time.time()
                self._hits += 1

            # Попытка десериализации в JSON
            try:
                return json.loads(payload_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return payload_bytes

        except (OSError, ValueError):
            # Поврежденная запись: fail-closed, инкремент счетчика и удаление
            with self._lock:
                self._corrupted_count += 1
                self._misses += 1
                self._current_bytes = max(0, self._current_bytes - self._entry_size(entry))
                if entry.file_path.exists() or entry.file_path.is_symlink():
                    entry.file_path.unlink(missing_ok=True)
                self._index.pop(key, None)
            return None

    def _ensure_capacity(self, needed_bytes: int, protected_key: str = "") -> bool:
        """LRU eviction while preserving an entry being atomically replaced."""
        if needed_bytes > self.max_bytes:
            return False
        while self._current_bytes + needed_bytes > self.max_bytes:
            eligible = [k for k in self._index if k != protected_key]
            if not eligible:
                return False
            lru_key = min(eligible, key=lambda k: self._index[k].last_accessed)
            victim = self._index[lru_key]
            try:
                if victim.file_path.is_symlink():
                    victim.file_path.unlink(missing_ok=True)
                    size = 0
                elif victim.file_path.exists():
                    size = victim.file_path.stat().st_size
                    victim.file_path.unlink(missing_ok=True)
                else:
                    raw_size = HEADER_SIZE + len(victim.payload_bytes)
                    size = ((raw_size + self.block_size - 1) // self.block_size) * self.block_size
            except OSError:
                return False
            self._index.pop(lru_key, None)
            self._current_bytes = max(0, self._current_bytes - size)
            self._evictions += 1
        return True

    def _scan_and_recover(self) -> None:
        """Сканирование директории кэша и восстановление индекса при старте."""
        self._index.clear()
        self._current_bytes = 0

        for file_path in self.cache_dir.glob("*.raifcache"):
            try:
                if file_path.is_symlink():
                    file_path.unlink(missing_ok=True)
                    continue
                with open(file_path, "rb") as f:
                    physical_size = os.fstat(f.fileno()).st_size
                    if (physical_size < HEADER_SIZE or physical_size > self.max_bytes or
                            physical_size % self.block_size != 0):
                        raise ValueError("Invalid cache-file length")
                    raw_header = f.read(HEADER_SIZE)
                    if len(raw_header) < HEADER_SIZE:
                        raise ValueError("Truncated header")
                    magic, ver, k_bytes, d_len, stored_crc, ts = HEADER_STRUCT.unpack(raw_header)
                    if magic != MAGIC_HEADER or ver != FORMAT_VERSION:
                        raise ValueError("Invalid cache header")
                    if (d_len > physical_size - HEADER_SIZE or
                            d_len > self.max_bytes - HEADER_SIZE):
                        raise ValueError("Oversized cache payload length")
                    key = k_bytes.hex()
                    if file_path.stem != key:
                        raise ValueError("Cache filename not bound to its key")
                    payload_bytes = f.read(d_len)
                    if len(payload_bytes) != d_len or (zlib.crc32(payload_bytes) & 0xFFFFFFFF) != stored_crc:
                        raise ValueError("Corrupted cache payload")

                entry = NvmeKVCacheEntry(
                    key=key,
                    model_id="recovered",
                    payload_bytes=payload_bytes,
                    checksum=stored_crc,
                    timestamp=ts,
                    file_path=file_path,
                )
                self._index[key] = entry
                self._current_bytes += physical_size
            except (OSError, ValueError):
                file_path.unlink(missing_ok=True)

    def get_metrics(self) -> Dict[str, Any]:
        """Телеметрия работы аппаратного кэша."""
        total_reqs = self._hits + self._misses
        hit_ratio = round((self._hits / total_reqs * 100), 2) if total_reqs > 0 else 0.0
        return {
            "entries_count": len(self._index),
            "current_bytes": self._current_bytes,
            "max_bytes": self.max_bytes,
            "hits": self._hits,
            "misses": self._misses,
            "hit_ratio_pct": hit_ratio,
            "evictions": self._evictions,
            "corrupted_detected": self._corrupted_count,
            "block_size": self.block_size,
        }

    def clear(self) -> None:
        """Полная очистка кэша."""
        with self._lock:
            self._staging_dict.clear()
            while not self._staging_queue.empty():
                try:
                    self._staging_queue.get_nowait()
                    self._staging_queue.task_done()
                except (queue.Empty, ValueError):
                    break
            for entry in self._index.values():
                if entry.file_path.exists():
                    entry.file_path.unlink(missing_ok=True)
            self._index.clear()
            self._current_bytes = 0

    def flush(self, wait: bool = True) -> None:
        """Сброс всех отложенных записей из очереди на диск (Milestone M1 / R6)."""
        if wait:
            self._staging_queue.join()

    def close(self) -> None:
        """Drain accepted items, stop worker, and avoid orphaned queue receipts."""
        if not self._worker_running:
            return
        self._worker_running = False
        # The consumer runs until the sentinel even when the flag is cleared.
        self._staging_queue.put(None)
        self._staging_queue.join()
        self._flush_thread.join(timeout=2.0)

    def __enter__(self) -> "NvmeKVCacheManager":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
