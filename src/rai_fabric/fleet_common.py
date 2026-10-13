# -*- coding: utf-8 -*-
"""
control.fleet_common - Каноническая библиотека переиспользуемых утилит флота CONTROL_TOWER.
Устраняет структурный AST-изоморфизм между репозиториями флота:
  1. Канонизация JSON (canonical_json) и детерминированное вычисление дайджестов (sha256_digest, sha256_text);
  2. Единый формат временных меток UTC (utc_now_iso);
  3. Атомарное безопасное сохранение и чтение JSON (atomic_write_json, load_json);
  4. Стандартизированный обработчик фатальных ошибок (fleet_fail).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.2) / Zero SSD Wear / RAM-First.
"""

from __future__ import annotations

__version__ = "1.0.0"

import os
import sys
import json
import hashlib
import datetime
import tempfile
from pathlib import Path
from typing import Any, Optional, NoReturn


def canonical_json(value: Any) -> str:
    """Детерминированная сериализация в компактный JSON со стабильным порядком ключей."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    """Вычисление SHA-256 хэша для произвольной последовательности байт."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Вычисление SHA-256 хэша для произвольной текстовой строки."""
    return sha256_bytes(text.encode("utf-8"))


def sha256_digest(value: Any) -> str:
    """Вычисление SHA-256 хэша для произвольной структуры данных через canonical_json."""
    return sha256_text(canonical_json(value))


def utc_now_iso() -> str:
    """Получение текущего времени UTC в стандартном ISO 8601 формате."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_json(path: Path | str, default: Any = None) -> Any:
    """Безопасное чтение JSON-файла с возвратом значения по умолчанию при отсутствии или ошибке."""
    target = Path(path)
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_write_json(path: Path | str, data: Any, indent: Optional[int] = 2) -> None:
    """Атомарная запись JSON через временный файл для защиты от повреждений при сбоях."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(dir=target.parent, prefix=f".tmp_{target.stem}_", suffix=".tmp")
    try:
        with open(temp_fd, "w", encoding="utf-8") as f:
            if indent is not None:
                json.dump(data, f, indent=indent, ensure_ascii=False)
            else:
                f.write(canonical_json(data))
        if target.exists():
            target.unlink()
        os.replace(temp_path, target)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise


def fleet_fail(message: str, exit_code: int = 1) -> NoReturn:
    """Стандартизированный аварийный выход для CLI скриптов и барьеров флота."""
    sys.stderr.write(f"[FATAL] {message}\n")
    sys.exit(exit_code)
