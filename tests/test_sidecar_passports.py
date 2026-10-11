# -*- coding: utf-8 -*-
"""
Тесты валидации sidecar-паспортов BPR40 v1.1 и каталогов Rassvet_AI_Fabric.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sidecar_passport_validator import SidecarPassportValidator


class TestSidecarPassports(unittest.TestCase):
    """Тесты валидации sidecar-паспортов BPR40 v1.1 и каталогов."""

    def test_scripts_sidecar_passports_valid(self):
        """Проверяет валидность всех Python sidecar-паспортов в scripts/."""
        validator = SidecarPassportValidator(repo_root=REPO_ROOT)
        scripts_dir = REPO_ROOT / "scripts"
        self.assertTrue(scripts_dir.exists(), "Директория scripts/ должна существовать")

        py_files = list(scripts_dir.glob("*.py"))
        self.assertGreaterEqual(len(py_files), 2, "В scripts/ должно быть не менее 2 модулей")

        violations = []
        for f in py_files:
            res = validator.validate_module(str(f))
            if not res["is_valid"]:
                violations.append((f.name, res["violations"]))

        self.assertFalse(violations, f"Обнаружены нарушения в scripts/: {violations}")

    def test_src_sidecar_passports_valid(self):
        """Проверяет валидность всех sidecar-паспортов в src/ (rai_fabric и raif_ag_supervisor)."""
        validator = SidecarPassportValidator(repo_root=REPO_ROOT)
        src_dir = REPO_ROOT / "src"
        self.assertTrue(src_dir.exists(), "Директория src/ должна существовать")

        py_files = sorted(src_dir.rglob("*.py"))
        self.assertEqual(len(py_files), 44, f"Ожидалось 44 модуля в src/, найдено {len(py_files)}")

        violations = []
        for f in py_files:
            res = validator.validate_module(str(f))
            if not res["is_valid"]:
                violations.append((str(f.relative_to(src_dir)), res["violations"]))

        self.assertFalse(violations, f"Обнаружены нарушения в src/: {violations}")

    def test_scripts_ps1_passports_exist(self):
        """Проверяет наличие и структуру sidecar-паспортов для всех PowerShell скриптов в scripts/."""
        scripts_dir = REPO_ROOT / "scripts"
        ps1_files = sorted(scripts_dir.glob("*.ps1"))
        self.assertEqual(len(ps1_files), 10, f"Ожидалось 10 скриптов PowerShell в scripts/, найдено {len(ps1_files)}")

        for ps1 in ps1_files:
            passport_file = scripts_dir / f"{ps1.stem}.passport.json"
            self.assertTrue(passport_file.exists(), f"Отсутствует sidecar-паспорт для {ps1.name}: {passport_file.name}")

            with open(passport_file, "r", encoding="utf-8") as pf:
                data = json.load(pf)

            self.assertEqual(data.get("schema"), "BPR40_SIDECAR_PASSPORT/1.1", f"Некорректная схема в {passport_file.name}")
            self.assertEqual(data.get("module_id"), ps1.stem, f"module_id должен совпадать со stem в {passport_file.name}")
            self.assertTrue("version" in data and data["version"], f"Поле version обязательно в {passport_file.name}")
            self.assertTrue("name" in data and data["name"], f"Поле name обязательно в {passport_file.name}")
            self.assertTrue("description" in data and data["description"], f"Поле description обязательно в {passport_file.name}")

    def test_catalogs_exist_and_populated(self):
        """Проверяет наличие и непустоту сгенерированных каталогов CATALOG.md."""
        catalogs = [
            REPO_ROOT / "scripts" / "CATALOG.md",
            REPO_ROOT / "src" / "CATALOG.md",
        ]

        for cat in catalogs:
            self.assertTrue(cat.exists(), f"Файл каталога {cat} должен существовать")
            content = cat.read_text(encoding="utf-8")
            self.assertIn("# Реестр скриптов", content, f"В {cat} отсутствует заголовок реестра")
            self.assertIn("## Оформленные скрипты", content, f"В {cat} отсутствует секция оформленных скриптов")
            self.assertGreaterEqual(len(content.splitlines()), 5, f"Каталог {cat} слишком короткий")


if __name__ == "__main__":
    unittest.main()
