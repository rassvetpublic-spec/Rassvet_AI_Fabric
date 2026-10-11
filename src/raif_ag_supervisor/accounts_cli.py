"""Windows-only local account vault operations with privacy-safe output.

User-supplied refresh tokens never leave this computer in this module.
No OAuth HTTP requests, no native Antigravity credential modifications,
no background account switching. Import requires an explicit confirmation.
"""
from __future__ import annotations

__version__ = "1.0.0"

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable

from .diagnostics import default_registry_dir
from .importer import ImportFormatError, inspect_file
from .registry import LocalAccountRegistry, RegistryError
from .windows_vault import WindowsCredentialVault

_MAX_INPUT = 1024 * 1024


def _reply(**status) -> None:
    print(json.dumps(status, ensure_ascii=True, sort_keys=True))


def _load_private_file(path: Path) -> bytes:
    """Do not put the source file into runtime, logs, Git or output archives."""
    with Path(path).open("rb") as handle:
        return handle.read(_MAX_INPUT + 1)


def main(
    argv: list[str] | None = None,
    *,
    vault_factory: Callable[[], object] = WindowsCredentialVault,
    registry_dir: Path | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="raif_ag_supervisor accounts",
        description="Локальные записи аккаунтов RAiF без вывода секретов",
    )
    parser.add_argument("--registry-dir", type=Path, default=None, help="Локальный каталог реестра RAiF")
    cmd = parser.add_subparsers(dest="command", required=True)
    preview = cmd.add_parser("preview", help="Проверить структуру файла без импорта")
    preview.add_argument("--file", type=Path, required=True)
    load = cmd.add_parser("import", help="Сохранить аккаунты в Credential Manager")
    load.add_argument("--file", type=Path, required=True)
    load.add_argument("--confirm-local-storage", action="store_true", required=False)
    cmd.add_parser("status", help="Подсчитать локально сохранённые записи")
    recover = cmd.add_parser("recover", help="Завершить или откатить незавершённый импорт")
    recover.add_argument("--confirm-recovery", action="store_true")
    opts = parser.parse_args(argv)

    try:
        if opts.command == "preview":
            count = inspect_file(opts.file)
            _reply(mode="preview", valid=True, accounts=count, secret_values_displayed=False)
            return 0

        if os.name != "nt":
            raise RuntimeError("unsupported operating system")

        directory = registry_dir or opts.registry_dir or default_registry_dir()
        # A status query must not create a new registry directory.
        if opts.command == "status" and not directory.is_dir():
            _reply(mode="status", registered_accounts=0, credentials_present=0,
                   recovery_required=False, secret_values_displayed=False)
            return 0
        if opts.command == "import" and not opts.confirm_local_storage:
            _reply(mode="import", status="confirmation_required", saved=False)
            return 3
        if opts.command == "recover" and not opts.confirm_recovery:
            _reply(mode="recover", status="confirmation_required", changed=False)
            return 3

        vault = vault_factory()
        registry = LocalAccountRegistry(directory)
        if opts.command == "status":
            handles = registry.ids()
            present = sum(1 for handle in handles if vault.has(handle))
            _reply(mode="status", registered_accounts=len(handles),
                   credentials_present=present,
                   recovery_required=registry.pending_path.exists(),
                   secret_values_displayed=False)
            return 0
        if opts.command == "recover":
            result = registry.recover(vault)
            _reply(mode="recover", result=result, secret_values_displayed=False)
            return 0
        if opts.command == "import":
            raw = _load_private_file(opts.file)
            handles = registry.import_manifest(raw, vault)
            _reply(mode="import", saved=True, accounts=len(handles),
                   credentials_present=len(handles), secret_values_displayed=False)
            return 0
    except (OSError, ValueError, ImportFormatError, RegistryError, RuntimeError):
        # Never include user-controlled paths, email, provider responses or tokens.
        print("ОШИБКА: операция не выполнена; данные не выводятся", file=sys.stderr)
        return 2
    return 2
