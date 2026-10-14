# -*- coding: utf-8 -*-
"""
control.fleet_common - Каноническая библиотека переиспользуемых утилит флота CONTROL_TOWER.
Устраняет структурный AST-изоморфизм между репозиториями флота:
  1. Канонизация JSON (canonical_json) и детерминированное вычисление дайджестов (sha256_digest, sha256_text);
  2. Единый формат временных меток UTC (utc_now_iso);
  3. Атомарное безопасное сохранение и чтение JSON (atomic_write_json, load_json);
  4. Строгий разбор JSON без дублирования ключей (unique_json_pairs, load_strict_json);
  5. Безопасное освобождение ресурсов (safe_close);
  6. Унифицированное извлечение заголовка (first_line);
  7. Стандартизированный обработчик фатальных ошибок (fleet_fail).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / Zero SSD Wear / RAM-First.
"""

from __future__ import annotations

__version__ = "1.4.0"

import os
import sys
import ast
import json
import hashlib
import datetime
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, NoReturn, Union, List, Callable


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


def first_line(body: Any) -> str:
    """Извлекает первую непустую строку из текста или строкового представления объекта."""
    lines = str(body or "").splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def unique_json_pairs(
    pairs: List[Tuple[str, Any]],
    error_factory: Optional[Callable[[str], Exception]] = None,
) -> Dict[str, Any]:
    """
    Хук для json.loads(object_pairs_hook=...), запрещающий дублирование ключей (RFC 7159).
    Вызывает исключение при обнаружении повторного поля.
    """
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            if error_factory is not None:
                raise error_factory(key)
            raise ValueError(f"Duplicate JSON key detected: '{key}'")
        result[key] = value
    return result


def make_unique_pairs_hook(
    error_factory: Callable[[str], Exception],
) -> Callable[[List[Tuple[str, Any]]], Dict[str, Any]]:
    """Создает object_pairs_hook для json.loads с кастомным генератором исключений."""
    def _hook(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        return unique_json_pairs(pairs, error_factory=error_factory)
    return _hook


def load_strict_json(raw: Union[str, bytes], limit: Optional[int] = None) -> Dict[str, Any]:
    """
    Строгий разбор JSON:
      - Проверяет лимит длины байт (если задан limit);
      - Запрещает дублирование ключей;
      - Запрещает нестандартные NaN / Infinity константы;
      - Гарантирует возвращение словаря (dict).
    """
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    else:
        raw_bytes = raw

    if limit is not None and len(raw_bytes) > limit:
        raise ValueError(f"JSON payload exceeds byte limit of {limit} bytes (got {len(raw_bytes)})")

    decoded_text = raw_bytes.decode("utf-8")
    parsed = json.loads(
        decoded_text,
        object_pairs_hook=unique_json_pairs,
        parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"Invalid JSON constant: {c}")),
    )
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object (dict), got {type(parsed).__name__}")
    return parsed


def safe_close(resource: Any) -> None:
    """Безопасное закрытие ресурсов без проброса исключений."""
    if resource is not None and hasattr(resource, "close") and callable(getattr(resource, "close")):
        try:
            resource.close()
        except Exception:
            pass


def extract_code_version(py_path: Path | str) -> Tuple[Optional[str], bool]:
    """Извлекает __version__ из AST и проверяет отсутствие устаревшего inline __passport__."""
    path = Path(py_path)
    if not path.exists():
        return None, False
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content, filename=str(path))
    except Exception:
        return None, False

    code_version = None
    has_inline_passport = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id == "__version__":
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            code_version = node.value.value
                    elif target.id == "__passport__":
                        has_inline_passport = True
    return code_version, has_inline_passport


def extract_python_docstring(py_path: Path | str) -> str:
    """Извлекает краткое описание Python-скрипта из sidecar-паспорта или docstring."""
    path = Path(py_path)
    sidecar = path.parent / f"{path.stem}.passport.json"
    if sidecar.exists():
        data = load_json(sidecar, default={})
        desc = data.get("description", "").strip() if isinstance(data, dict) else ""
        if desc and desc != f"Модуль {path.stem}":
            return desc
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        module = ast.parse(content)
        doc = ast.get_docstring(module)
        if doc and doc.strip():
            return doc.strip().split("\n")[0]
        # Поиск первых комментариев
        comments = []
        for line in content.splitlines():
            line_s = line.strip()
            if line_s.startswith("#") and not line_s.startswith("#!") and "coding:" not in line_s:
                c = line_s.lstrip("#").strip()
                if c:
                    comments.append(c)
            elif comments and not line_s.startswith("#"):
                break
        if comments:
            return " ".join(comments)[:100]
    except Exception:
        pass
    return "_Описание отсутствует_"


def load_sidecar_passport(py_path: Path | str) -> Optional[Dict[str, Any]]:
    """Загружает sidecar-паспорт для указанного Python-модуля при его наличии."""
    path = Path(py_path)
    sidecar = path.parent / f"{path.stem}.passport.json"
    if sidecar.exists():
        data = load_json(sidecar)
        if isinstance(data, dict):
            return data
    return None


def get_repo_root(anchor: Path | str | None = None) -> Path:
    """Универсальное определение корня репозитория по маркеру .git или переданному якорю."""
    current = Path(anchor).resolve() if anchor else Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists():
            return parent
    return current.parent


def read_cli_body(path: str) -> str:
    """Безопасное чтение тела запроса из файла или stdin ('-')."""
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def write_cli_json_result(result: Dict[str, Any], output: Optional[Path | str] = None) -> None:
    """Унифицированный вывод JSON результата в файл или stdout."""
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def safe_dict(obj: Any) -> Dict[str, Any]:
    """Безопасное приведение объекта к словарю без утечки приватных полей."""
    if hasattr(obj, "safe_dict") and callable(obj.safe_dict):
        return obj.safe_dict()
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if not str(k).startswith("_")}
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not str(k).startswith("_")}
    return {"value": str(obj)}


def safe_int(val: Any, default: int = 0) -> int:
    """Безопасное преобразование значения в целое число без возбуждения исключений."""
    try:
        if val is None:
            return default
        return int(float(val))
    except (ValueError, TypeError, OverflowError):
        return default


def safe_float(val: Any, default: float = 0.0) -> float:
    """Безопасное преобразование значения в число с плавающей точкой без исключений."""
    try:
        if val is None:
            return default
        return float(val)
    except (ValueError, TypeError, OverflowError):
        return default


def format_bytes(num_bytes: Union[int, float]) -> str:
    """Форматирует размер в байтах в человекочитаемый вид (B, KB, MB, GB, TB)."""
    try:
        n = float(num_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(n) < 1024.0 or unit == "TB":
                return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
            n /= 1024.0
        return f"{n:.2f} TB"
    except Exception:
        return "0 B"


def ensure_dir(path: Union[str, Path]) -> Path:
    """Гарантирует существование директории (mkdir parents=True, exist_ok=True)."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

