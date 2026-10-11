# -*- coding: utf-8 -*-
"""
Тесты валидации sidecar-паспортов BPR40 v1.1 и каталогов Rassvet_AI_Fabric.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sidecar_passport_validator import SidecarPassportValidator


def test_scripts_sidecar_passports_valid():
    """Проверяет валидность всех Python sidecar-паспортов в scripts/."""
    validator = SidecarPassportValidator(repo_root=REPO_ROOT)
    scripts_dir = REPO_ROOT / "scripts"
    assert scripts_dir.exists(), "Директория scripts/ должна существовать"

    py_files = list(scripts_dir.glob("*.py"))
    assert len(py_files) >= 2, "В scripts/ должно быть не менее 2 модулей"

    violations = []
    for f in py_files:
        res = validator.validate_module(str(f))
        if not res["is_valid"]:
            violations.append((f.name, res["violations"]))

    assert not violations, f"Обнаружены нарушения в scripts/: {violations}"


def test_src_sidecar_passports_valid():
    """Проверяет валидность всех sidecar-паспортов в src/ (rai_fabric и raif_ag_supervisor)."""
    validator = SidecarPassportValidator(repo_root=REPO_ROOT)
    src_dir = REPO_ROOT / "src"
    assert src_dir.exists(), "Директория src/ должна существовать"

    py_files = sorted(src_dir.rglob("*.py"))
    assert len(py_files) == 43, f"Ожидалось 43 модуля в src/, найдено {len(py_files)}"

    violations = []
    for f in py_files:
        res = validator.validate_module(str(f))
        if not res["is_valid"]:
            violations.append((str(f.relative_to(src_dir)), res["violations"]))

    assert not violations, f"Обнаружены нарушения в src/: {violations}"


def test_scripts_ps1_passports_exist():
    """Проверяет наличие и структуру sidecar-паспортов для всех PowerShell скриптов в scripts/."""
    scripts_dir = REPO_ROOT / "scripts"
    ps1_files = sorted(scripts_dir.glob("*.ps1"))
    assert len(ps1_files) == 10, f"Ожидалось 10 скриптов PowerShell в scripts/, найдено {len(ps1_files)}"

    for ps1 in ps1_files:
        passport_file = scripts_dir / f"{ps1.stem}.passport.json"
        assert passport_file.exists(), f"Отсутствует sidecar-паспорт для {ps1.name}: {passport_file.name}"

        with open(passport_file, "r", encoding="utf-8") as pf:
            data = json.load(pf)

        assert data.get("schema") == "BPR40_SIDECAR_PASSPORT/1.1", f"Некорректная схема в {passport_file.name}"
        assert data.get("module_id") == ps1.stem, f"module_id должен совпадать со stem в {passport_file.name}"
        assert "version" in data and data["version"], f"Поле version обязательно в {passport_file.name}"
        assert "name" in data and data["name"], f"Поле name обязательно в {passport_file.name}"
        assert "description" in data and data["description"], f"Поле description обязательно в {passport_file.name}"


def test_catalogs_exist_and_populated():
    """Проверяет наличие и непустоту сгенерированных каталогов CATALOG.md."""
    catalogs = [
        REPO_ROOT / "scripts" / "CATALOG.md",
        REPO_ROOT / "src" / "CATALOG.md",
    ]

    for cat in catalogs:
        assert cat.exists(), f"Файл каталога {cat} должен существовать"
        content = cat.read_text(encoding="utf-8")
        assert "# Реестр скриптов" in content, f"В {cat} отсутствует заголовок реестра"
        assert "## Оформленные скрипты" in content, f"В {cat} отсутствует секция оформленных скриптов"
        assert len(content.splitlines()) >= 5, f"Каталог {cat} слишком короткий"
