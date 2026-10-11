# -*- coding: utf-8 -*-
"""Регрессионная приёмка BPR40 sidecar и каталогов штатным unittest.

Один и тот же набор должен обнаруживаться в Windows CI и в локальном
python -m unittest discover -s tests -v; зависимости от pytest нет.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import sidecar_passport_validator as sidecars
from scripts.sidecar_passport_validator import SidecarPassportValidator


class RepositorySidecarTests(unittest.TestCase):
    def setUp(self):
        self.validator = SidecarPassportValidator(repo_root=REPO_ROOT)

    def test_scripts_sidecar_passports_valid(self):
        scripts_dir = REPO_ROOT / "scripts"
        self.assertTrue(scripts_dir.is_dir())
        python_files = sorted(scripts_dir.glob("*.py"))
        self.assertGreaterEqual(len(python_files), 2)
        violations = [(p.name, result["violations"])
                      for p in python_files
                      if not (result := self.validator.validate_module(str(p)))["is_valid"]]
        self.assertEqual(violations, [], str(violations))

    def test_src_sidecar_passports_valid(self):
        src_dir = REPO_ROOT / "src"
        python_files = sorted(src_dir.rglob("*.py"))
        passport_files = sorted(src_dir.rglob("*.passport.json"))
        # 43 existing modules plus PR #5's host diagnostic. Count is a floor,
        # not a fixed limit that breaks each future addition.
        self.assertGreaterEqual(len(python_files), 44)
        self.assertEqual(len(passport_files), len(python_files))
        violations = [(str(p.relative_to(src_dir)), result["violations"])
                      for p in python_files
                      if not (result := self.validator.validate_module(str(p)))["is_valid"]]
        self.assertEqual(violations, [], str(violations))
        self.assertTrue((src_dir / "rai_fabric" / "host_diagnostic_10_3.passport.json").is_file())

    def test_scripts_ps1_passports_exist(self):
        scripts_dir = REPO_ROOT / "scripts"
        powershell = sorted(scripts_dir.glob("*.ps1"))
        self.assertEqual(len(powershell), 10)
        for script in powershell:
            with self.subTest(script=script.name):
                passport = scripts_dir / (script.stem + ".passport.json")
                self.assertTrue(passport.is_file())
                data = json.loads(passport.read_text(encoding="utf-8"))
                self.assertEqual(data.get("schema"), "BPR40_SIDECAR_PASSPORT/1.1")
                self.assertEqual(data.get("module_id"), script.stem)
                for key in ("version", "name", "description"):
                    self.assertTrue(data.get(key), key)

    def test_catalogs_exist_and_populated(self):
        for directory in ("scripts", "src"):
            with self.subTest(directory=directory):
                catalog = REPO_ROOT / directory / "CATALOG.md"
                self.assertTrue(catalog.is_file())
                body = catalog.read_text(encoding="utf-8")
                self.assertIn("# Реестр скриптов", body)
                self.assertIn("## Оформленные скрипты", body)
                self.assertGreaterEqual(len(body.splitlines()), 5)
        self.assertIn("rai_fabric/host_diagnostic_10_3.py",
                      (REPO_ROOT / "src" / "CATALOG.md").read_text(encoding="utf-8"))

    def test_package_version_consistent_with_pyproject(self):
        import rai_fabric
        metadata = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(rai_fabric.__version__, metadata["project"]["version"])
        passport = json.loads((REPO_ROOT / "src" / "rai_fabric" /
                               "__init__.passport.json").read_text(encoding="utf-8"))
        self.assertEqual(passport["version"], rai_fabric.__version__)


class NegativeSidecarContractTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="raif-passport-qa-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.module = self.root / "fixture.py"
        self.module.write_text(
            '__version__ = "1.0.0"\n'
            'def run(path: str, *items: str, label: str = "ok", **options: object) -> None:\n'
            '    pass\n', encoding="utf-8"
        )
        self.sidecar = self.root / "fixture.passport.json"
        self.valid = {"schema": "BPR40_SIDECAR_PASSPORT/1.1",
                      "version": "1.0.0", "module_id": "fixture",
                      "functions": {"run": {"args": ["path", "*items", "label", "**options"]}}}
        self.validator = SidecarPassportValidator(repo_root=self.root)
        self.write_passport(self.valid)

    def write_passport(self, payload):
        self.sidecar.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def assert_blocked(self, expected_rule):
        result = self.validator.validate_module(str(self.module))
        self.assertFalse(result["is_valid"], result)
        self.assertIn(expected_rule, [v["rule"] for v in result["violations"]])

    def test_correct_variadic_contract_passes(self):
        self.assertTrue(self.validator.validate_module(str(self.module))["is_valid"])
        signatures = self.validator.extract_functions_from_ast(self.module)
        self.assertEqual(signatures["run"]["args"],
                         ["path", "*items", "label", "**options"])
        self.assertEqual(signatures["run"]["inputs"]["items"]["kind"], "VAR_POSITIONAL")
        self.assertEqual(signatures["run"]["inputs"]["options"]["kind"], "VAR_KEYWORD")

    def test_wrong_schema_is_invalid(self):
        changed = {**self.valid, "schema": "WRONG"}
        self.write_passport(changed)
        self.assert_blocked("INVALID_SIDECAR_SCHEMA")

    def test_nonobject_root_is_invalid(self):
        self.write_passport(["not", "a", "passport"])
        self.assert_blocked("INVALID_SIDECAR_ROOT")

    def test_p1_missing_id_blocks(self):
        self.write_passport({k: v for k, v in self.valid.items() if k != "module_id"})
        self.assert_blocked("MISSING_MODULE_ID")

    def test_p1_mismatched_id_blocks(self):
        self.write_passport({**self.valid, "module_id": "other"})
        self.assert_blocked("MODULE_ID_MISMATCH")

    def test_p1_missing_function_blocks(self):
        self.write_passport({**self.valid, "functions": {"deleted": {"args": []}}})
        self.assert_blocked("FUNCTION_NOT_FOUND")

    def test_deprecated_inline_passport_blocks(self):
        self.module.write_text(self.module.read_text(encoding="utf-8")
                               + "\n__passport__ = {}\n", encoding="utf-8")
        self.assert_blocked("DEPRECATED_INLINE_PASSPORT")

    def test_variadic_contract_drift_blocks(self):
        self.write_passport({**self.valid, "functions": {"run":
                            {"args": ["path", "label"]}}})
        self.assert_blocked("CONTRACT_DRIFT")

    def test_corrupt_enrichment_preserves_bytes(self):
        original = b'{"schema": "BPR40_SIDECAR_PASSPORT/1.1", BAD JSON'
        self.sidecar.write_bytes(original)
        self.assertIsNone(self.validator.enrich_sidecar_with_functions(str(self.module)))
        self.assertEqual(self.sidecar.read_bytes(), original)

    def test_corrupt_enrichment_cli_fails_without_mutation(self):
        original = b"not-json-private-bytes"
        self.sidecar.write_bytes(original)
        err = io.StringIO()
        argv = ["sidecar_passport_validator", str(self.module),
                "--enrich-functions", "--repo-root", str(self.root)]
        with patch.object(sys, "argv", argv), contextlib.redirect_stderr(err):
            exit_code = sidecars.main()
        self.assertEqual(exit_code, 1)
        self.assertIn("отклонено", err.getvalue())
        self.assertNotIn("private-bytes", err.getvalue())
        self.assertEqual(self.sidecar.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
