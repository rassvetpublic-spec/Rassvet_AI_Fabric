"""Явное локальное управление: задания и токены не отправляются в API без согласия."""
from __future__ import annotations

__version__ = "1.0.0"

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .gateway import Gateway
from .mcp_server import MCPStdioServer
from .store import FabricError, FabricStore
from .worker import run_one


class RAIArgumentParser(argparse.ArgumentParser):
    """Русские заголовки справки без изменения контрактных CLI-аргументов."""

    def __init__(self, *args: Any, **kwargs: Any):
        kwargs.setdefault("add_help", False)
        super().__init__(*args, **kwargs)
        self._positionals.title = "Позиционные аргументы"
        self._optionals.title = "Параметры"
        self.add_argument("-h", "--help", action="help", help="Показать справку и выйти")

    def format_help(self) -> str:
        value = super().format_help()
        return value.replace("usage: ", "Использование: ").replace(
            "positional arguments:", "Позиционные аргументы:").replace("options:", "Параметры:")

    def error(self, message: str) -> None:
        # Переводим сообщения argparse, не меняя имена обязательных параметров.
        if message.startswith("the following arguments are required:"):
            message = "не указаны обязательные аргументы:" + message.split(":", 1)[1]
        elif message.startswith("argument ") and "invalid choice:" in message:
            message = message.replace("invalid choice:", "недопустимое значение:")
        elif message.startswith("unrecognized arguments:"):
            message = message.replace("unrecognized arguments:", "неизвестные аргументы:")
        message = message.replace("argument ", "аргумент ")
        message = message.replace("(choose from ", "(допустимые варианты: ")
        message = message.replace("expected one argument", "требуется значение аргумента")
        self.exit(2, f"ОШИБКА: {message}\n")


def parser() -> argparse.ArgumentParser:
    p = RAIArgumentParser(prog="rai", description="Rassvet AI Fabric 0.1.0 — независимое локальное ядро задач")
    p.add_argument("--db", required=True, help="Путь к отдельной БД SQLite; не используйте хранилища BPR40 и Codex")
    subs = p.add_subparsers(dest="action", required=True, parser_class=RAIArgumentParser, title="Команды", metavar="КОМАНДА")
    subs.add_parser("init", help="Создать отдельную БД задач по явной команде")
    cmd = subs.add_parser("submit", help="Добавить задачу в очередь")
    cmd.add_argument("--objective", required=True, help="Описание задачи")
    cmd.add_argument("--provider", choices=["mock", "codex-mock", "antigravity", "codex-app"], default="mock", help="Исполнитель; по умолчанию mock")
    cmd.add_argument("--workspace", required=True, help="Путь к разрешённому рабочему каталогу")
    cmd.add_argument("--task-id", help="Собственный идентификатор задачи")
    cmd.add_argument("--depends-on", action="append", default=[], help="Идентификатор зависимости; можно повторять")
    cmd = subs.add_parser("tasks", help="Показать список задач")
    cmd.add_argument("--limit", type=int, default=50, help="Максимальное число задач")
    cmd = subs.add_parser("task", help="Показать задачу по идентификатору")
    cmd.add_argument("id", help="Идентификатор задачи")
    cmd = subs.add_parser("events", help="Показать журнал событий задачи")
    cmd.add_argument("id", help="Идентификатор задачи")
    cmd = subs.add_parser("claim", help="Выдать готовую задачу исполнителю")
    cmd.add_argument("--owner", required=True, help="Идентификатор исполнителя")
    cmd.add_argument("--provider", choices=["mock", "codex-mock", "antigravity", "codex-app"], help="Фильтр по исполнителю")
    cmd.add_argument("--lease-seconds", type=int, default=120, help="Длительность аренды в секундах")
    cmd = subs.add_parser("heartbeat", help="Продлить аренду задачи")
    cmd.add_argument("id", help="Идентификатор задачи")
    cmd.add_argument("--owner", required=True, help="Идентификатор исполнителя")
    cmd.add_argument("--lease-seconds", type=int, default=120, help="Длительность аренды в секундах")
    cmd = subs.add_parser("checkpoint", help="Записать проверяемый чекпойнт")
    cmd.add_argument("id", help="Идентификатор задачи")
    cmd.add_argument("--owner", required=True, help="Идентификатор исполнителя")
    cmd.add_argument("--stage", required=True, help="Идентификатор этапа")
    cmd.add_argument("--cursor", required=True, help="Курсор следующего действия")
    cmd.add_argument("--verdict", choices=["PASS", "PARTIAL", "BLOCKED"], default="PARTIAL", help="Статус проверки чекпойнта")
    cmd.add_argument("--evidence", default="{}", help="Объект JSON с доказательствами")
    cmd = subs.add_parser("finish", help="Завершить задачу и записать результат")
    cmd.add_argument("id", help="Идентификатор задачи")
    cmd.add_argument("--owner", required=True, help="Идентификатор исполнителя")
    cmd.add_argument("--verdict", choices=["PASS", "PARTIAL", "BLOCKED"], required=True, help="Итог исполнения")
    cmd.add_argument("--response", required=True, help="Текст результата")
    cmd.add_argument("--cursor", default="REVIEW", help="Следующий курсор; по умолчанию REVIEW")
    cmd.add_argument("--evidence", default="{}", help="Объект JSON с доказательствами")
    cmd = subs.add_parser("result", help="Получить результат задачи")
    cmd.add_argument("id", help="Идентификатор задачи")
    subs.add_parser("recover", help="Пометить задачи с истёкшей арендой для ручной сверки")
    cmd = subs.add_parser("requeue", help="Вернуть задачу в очередь после сверки")
    cmd.add_argument("id", help="Идентификатор задачи")
    cmd.add_argument("--acknowledge", required=True, help="Подтверждение проверки побочных эффектов")
    cmd = subs.add_parser("cancel", help="Запросить отмену задачи")
    cmd.add_argument("id", help="Идентификатор задачи")
    cmd = subs.add_parser("confirm-cancel", help="Подтвердить отмену действующим исполнителем")
    cmd.add_argument("id", help="Идентификатор задачи")
    cmd.add_argument("--owner", required=True, help="Идентификатор исполнителя")
    cmd = subs.add_parser("run-once", help="Выполнить одну готовую задачу")
    cmd.add_argument("--provider", choices=["mock", "codex-mock", "antigravity", "codex-app"], required=True, help="Исполнитель для одного запуска")
    cmd.add_argument("--allow-external", action="store_true", help="Явно разрешить внешний запуск исполнителя")
    cmd.add_argument("--timeout", type=int, default=300, help="Ограничение времени исполнения в секундах")
    cmd = subs.add_parser("mcp", help="Запустить локальный MCP-сервер по stdio")
    cmd.add_argument("--workspace", required=True, help="Путь к разрешённому рабочему каталогу")
    return p


def _evidence(value: str) -> dict[str, Any]:
    data = json.loads(value)
    if not isinstance(data, dict):
        raise FabricError("Доказательства должны быть объектом JSON")
    return data


def _token() -> str:
    # Не передавайте токены аренды в аргументах командной строки.
    value = os.environ.get("RAI_LEASE_TOKEN", "")
    if not value:
        raise FabricError("Требуется переменная окружения RAI_LEASE_TOKEN")
    return value


def run(argv: list[str] | None = None) -> Any:
    a = parser().parse_args(argv)
    with FabricStore(a.db, initialize=(a.action == "init")) as s:
        if a.action == "init":
            return {"initialized": True, "database": str(s.path), "schema_version": 1}
        if a.action == "submit":
            return s.submit(a.objective, a.provider, a.workspace,
                            task_id=a.task_id, depends_on=a.depends_on)
        if a.action == "tasks":
            return {"tasks": s.list(a.limit)}
        if a.action == "task":
            return s.get(a.id)
        if a.action == "events":
            return {"events": s.events(a.id)}
        if a.action == "result":
            return s.result(a.id)
        if a.action == "claim":
            return s.claim(a.owner, provider=a.provider, lease_seconds=a.lease_seconds)
        if a.action == "heartbeat":
            return s.heartbeat(a.id, a.owner, _token(), lease_seconds=a.lease_seconds)
        if a.action == "checkpoint":
            return s.checkpoint(a.id, a.owner, _token(), a.stage, a.cursor,
                                _evidence(a.evidence), a.verdict)
        if a.action == "finish":
            return s.finish(a.id, a.owner, _token(), verdict=a.verdict, response=a.response,
                            evidence=_evidence(a.evidence), cursor=a.cursor)
        if a.action == "recover":
            return {"blocked_for_reconciliation": s.recover()}
        if a.action == "requeue":
            return s.requeue(a.id, acknowledgement=a.acknowledge)
        if a.action == "cancel":
            return s.request_cancel(a.id)
        if a.action == "confirm-cancel":
            return s.confirm_cancel(a.id, a.owner, _token())
        if a.action == "run-once":
            return run_one(s, a.provider, allow_external=a.allow_external, timeout_seconds=a.timeout)
        if a.action == "mcp":
            MCPStdioServer(Gateway(s, a.workspace)).serve()
            return None
    raise FabricError("Неизвестная команда")


def main() -> None:
    try:
        result = run()
        if result is not None:
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    except (FabricError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
