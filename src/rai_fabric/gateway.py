"""Локальный шлюз инструментов только для чтения, без произвольных shell-команд."""
from __future__ import annotations

__version__ = "1.0.0"

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .store import FabricError, FabricStore

_MAX_TEXT_BYTES = 32768
_FORBIDDEN_PARTS = {".git", ".ssh", ".codex", ".config", "node_modules",
                    ".rai-fabric", "__pycache__", ".venv", "venv"}
_FORBIDDEN_NAMES = {".env", "auth.json", "credentials.json", "id_rsa", "id_ed25519",
                    "config.toml", "known_hosts", "cookies.sqlite"}
_FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3", ".jks"}


class Gateway:
    def __init__(self, store: FabricStore, workspace: str | Path):
        self.store = store
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise FabricError("Рабочий каталог должен существовать")

    def _safe_path(self, relative: str) -> Path:
        if not isinstance(relative, str) or len(relative) > 2048 or "\x00" in relative:
            raise FabricError("Некорректный относительный путь")
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise FabricError("Разрешены только относительные пути внутри рабочего каталога")
        if any(part.casefold() in _FORBIDDEN_PARTS for part in candidate.parts):
            raise FabricError("Доступ к защищённому каталогу запрещён")
        name = candidate.name.casefold()
        if (name in _FORBIDDEN_NAMES or name.startswith(".env") or
            name.endswith((".db-wal", ".db-shm", ".db-journal", ".sqlite-wal", ".sqlite-shm",
                           ".sqlite3-wal", ".sqlite3-shm")) or
            candidate.suffix.casefold() in _FORBIDDEN_SUFFIXES):
            raise FabricError("Доступ к защищённому файлу запрещён")
        unresolved = self.workspace / candidate
        # Запрещаем проход через ссылки и точки перенаправления Windows.
        cur = self.workspace
        for part in candidate.parts:
            cur = cur / part
            if cur.is_symlink() or (hasattr(cur, "is_junction") and cur.is_junction()):
                raise FabricError("Ссылки и junction недоступны через MCP")
        resolved = unresolved.resolve(strict=True)
        if not resolved.is_relative_to(self.workspace):
            raise FabricError("Путь выходит за пределы рабочего каталога после разрешения ссылок")
        rel = resolved.relative_to(self.workspace)
        if any(part.casefold() in _FORBIDDEN_PARTS for part in rel.parts):
            raise FabricError("Доступ к защищённому конечному каталогу запрещён")
        rname = rel.name.casefold()
        if (rname in _FORBIDDEN_NAMES or rname.startswith(".env") or
            rname.endswith((".db-wal", ".db-shm", ".db-journal", ".sqlite-wal", ".sqlite-shm",
                            ".sqlite3-wal", ".sqlite3-shm")) or
            rel.suffix.casefold() in _FORBIDDEN_SUFFIXES):
            raise FabricError("Доступ к защищённому конечному файлу запрещён")
        return resolved

    def health(self) -> dict[str, Any]:
        return {"server": "rassvet-ai-fabric", "version": "0.1.0", "mode": "read-only",
                "workspace": str(self.workspace)}

    def read_file(self, path: str) -> dict[str, Any]:
        file = self._safe_path(path)
        if not file.is_file():
            raise FabricError("Указанный путь не является обычным файлом")
        if file.stat().st_size > _MAX_TEXT_BYTES:
            raise FabricError(f"Размер файла превышает лимит MCP на чтение: {_MAX_TEXT_BYTES} байт")
        data = file.read_bytes()
        if b"\x00" in data:
            raise FabricError("Чтение бинарных файлов через этот шлюз запрещено")
        return {"path": str(file.relative_to(self.workspace)), "text": data.decode("utf-8"),
                "bytes": len(data)}

    def list_files(self, path: str = ".", limit: int = 50) -> dict[str, Any]:
        directory = self._safe_path(path)
        if not directory.is_dir():
            raise FabricError("Указанный путь не является каталогом")
        limit = max(1, min(int(limit), 100))
        result = []
        for item in sorted(directory.iterdir(), key=lambda p: p.name.casefold()):
            try:
                safe = self._safe_path(str(item.relative_to(self.workspace)))
            except (FabricError, FileNotFoundError, PermissionError):
                continue
            if safe.is_file() or safe.is_dir():
                result.append({"name": item.name, "type": "directory" if safe.is_dir() else "file"})
            if len(result) >= limit:
                break
        return {"path": path, "entries": result, "max_items": limit}

    def git_status(self) -> dict[str, Any]:
        if not shutil.which("git"):
            return {"available": False}
        result = subprocess.run(["git", "-C", str(self.workspace), "status", "--porcelain", "--untracked-files=no"],
                                capture_output=True, text=True, timeout=5, check=False)
        return {"available": result.returncode == 0,
                "status": result.stdout[:_MAX_TEXT_BYTES], "error": result.stderr[-500:] if result.returncode else ""}

    def gpu_status(self) -> dict[str, Any]:
        executable = shutil.which("nvidia-smi")
        if not executable:
            return {"available": False, "reason": "Утилита nvidia-smi не обнаружена в PATH"}
        args = [executable, "--query-gpu=name,memory.total,memory.free,utilization.gpu", "--format=csv,noheader,nounits"]
        result = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)
        return {"available": result.returncode == 0, "gpu": result.stdout.strip()[:1000],
                "error": result.stderr[-300:] if result.returncode else ""}

    def invoke(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "rai_health":
            return self.health()
        if name == "rai_tasks_list":
            return {"tasks": self.store.list(int(args.get("limit", 30)))}
        if name == "rai_task_get":
            return self.store.get(str(args["task_id"]))
        if name == "rai_checkpoint_latest":
            return {"checkpoint": self.store.latest_checkpoint(str(args["task_id"]))}
        if name == "rai_workspace_list":
            return self.list_files(str(args.get("path", ".")), int(args.get("limit", 50)))
        if name == "rai_workspace_read":
            return self.read_file(str(args["path"]))
        if name == "rai_git_status":
            return self.git_status()
        if name == "rai_gpu_status":
            return self.gpu_status()
        raise FabricError("Неизвестный MCP-инструмент")


def tools_manifest() -> list[dict[str, Any]]:
    def spec(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None):
        return {"name": name, "description": description,
                "inputSchema": {"type": "object", "properties": properties,
                                "required": required or [], "additionalProperties": False}}
    return [
        spec("rai_health", "Показать состояние сервиса; без данных авторизации", {}),
        spec("rai_tasks_list", "Получить список задач без токенов аренды", {"limit": {"type": "integer"}}),
        spec("rai_task_get", "Прочитать задачу и последний чекпойнт", {"task_id": {"type": "string"}}, ["task_id"]),
        spec("rai_checkpoint_latest", "Прочитать и проверить контрольную сумму последнего чекпойнта", {"task_id": {"type": "string"}}, ["task_id"]),
        spec("rai_workspace_list", "Показать разрешённые файлы рабочего каталога", {"path": {"type": "string"}, "limit": {"type": "integer"}}),
        spec("rai_workspace_read", "Прочитать разрешённый UTF-8-файл размером до 32 КиБ", {"path": {"type": "string"}}, ["path"]),
        spec("rai_git_status", "Показать состояние рабочего дерева Git без изменений", {}),
        spec("rai_gpu_status", "Показать диагностику nvidia-smi (вывод моделей ещё не реализован)", {}),
    ]
