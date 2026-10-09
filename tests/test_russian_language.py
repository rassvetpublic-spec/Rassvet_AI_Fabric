"""Проверки официального русского языка проекта и стабильности протокола."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from rai_fabric.cli import parser
from rai_fabric.gateway import Gateway, tools_manifest
from rai_fabric.mcp_server import MCPStdioServer
from rai_fabric.store import FabricError, FabricStore
from rai_fabric.worker import run_one


class RussianLanguageTests(unittest.TestCase):
    def test_cli_root_and_command_help_are_russian(self):
        for args, expected in [(["--help"], "Показать справку"),
                               (["submit", "--help"], "Описание задачи")]:
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream), self.assertRaises(SystemExit) as exit_code:
                parser().parse_args(args)
            self.assertEqual(exit_code.exception.code, 0)
            self.assertIn(expected, stream.getvalue())
            self.assertIn("Использование:", stream.getvalue())

    def test_cli_errors_are_russian_without_renaming_options(self):
        with contextlib.redirect_stderr(io.StringIO()) as stream:
            with self.assertRaises(SystemExit):
                parser().parse_args(["--db", "state.db", "unknown-command"])
        self.assertIn("ОШИБКА:", stream.getvalue())
        self.assertIn("недопустимое значение", stream.getvalue())

    def test_mcp_descriptions_are_russian_and_identifiers_stable(self):
        items = tools_manifest()
        self.assertEqual(len(items), 8)
        self.assertTrue(all(any("А" <= char <= "я" for char in x["description"]) for x in items))
        self.assertIn("rai_workspace_read", [x["name"] for x in items])
        with tempfile.TemporaryDirectory() as tmp:
            with FabricStore(Path(tmp) / "test.db", initialize=True) as db:
                server = MCPStdioServer(Gateway(db, tmp))
                r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": "2025-11-25"}})
                self.assertIn("только для чтения", r["result"]["instructions"].lower())
                self.assertEqual(r["result"]["protocolVersion"], "2025-11-25")

    def test_errors_and_mock_result_are_russian(self):
        with tempfile.TemporaryDirectory() as tmp:
            with FabricStore(Path(tmp) / "state.db", initialize=True) as db:
                with self.assertRaises(FabricError) as caught:
                    db.get("does-not-exist")
                self.assertIn("Задача не найдена", str(caught.exception))
                db.submit("Проверка локализации", "mock", tmp, task_id="ru-fixture")
                result = run_one(db, "mock")
                self.assertEqual(result["status"], "COMPLETE")
                self.assertIn("Имитатор принял задачу", db.result("ru-fixture")["response"])
                self.assertEqual(result["checkpoint"]["cursor"], "REVIEW")

    def test_documentation_sets_ru_as_official_language(self):
        docs = Path(__file__).resolve().parents[1]
        primary = (docs / "README.md").read_text(encoding="utf-8")
        policy = (docs / "docs/LANGUAGE_POLICY.md").read_text(encoding="utf-8")
        self.assertIn("Официальный язык проекта — русский", primary)
        self.assertIn("обязательное правило проекта", policy)


if __name__ == "__main__":
    unittest.main()
