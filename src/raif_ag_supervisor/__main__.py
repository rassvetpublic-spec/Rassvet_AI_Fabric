"""Minimal non-destructive command line interface for RAiF AG Supervisor."""
from __future__ import annotations

__version__ = "1.0.0"

import argparse
import json
import sys
from pathlib import Path

from .diagnostics import default_registry_dir, readonly_status
from .registry import RegistryError
from .accounts_cli import main as accounts_main
from .pool import synthetic_demo


def main(argv: list[str] | None = None) -> int:
    parameters = sys.argv[1:] if argv is None else list(argv)
    if parameters and parameters[0] == "accounts":
        return accounts_main(parameters[1:])
    if parameters == ["pool-demo"]:
        print(json.dumps(synthetic_demo(), ensure_ascii=True, sort_keys=True))
        return 0
    parser = argparse.ArgumentParser(
        prog="raif_ag_supervisor",
        description="Безопасная диагностика Antigravity Standalone без чтения токенов",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="Показать процессы и состояние локального реестра")
    status.add_argument(
        "--registry-dir", type=Path, default=None,
        help="Папка собственного реестра RAiF (по умолчанию LOCALAPPDATA/RAiF/AGSupervisor)",
    )
    args = parser.parse_args(parameters)
    if args.command != "status":
        parser.error("Неизвестная команда")
    try:
        registry_dir = args.registry_dir if args.registry_dir is not None else default_registry_dir()
        result = readonly_status(registry_dir)
    except (OSError, RegistryError, ValueError):
        print("ОШИБКА: невозможно безопасно прочитать состояние", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
