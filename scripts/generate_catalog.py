# -*- coding: utf-8 -*-
"""
Автоматический генератор каталога скриптов (CATALOG.md) по стандарту CONTROL_TOWER / BPR40.
Поддерживает извлечение описания из Python docstring, PowerShell help-блока и sidecar-паспортов.
"""
from __future__ import annotations

__version__ = "1.0.0"

import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]


def extract_python_doc(filepath: Path) -> str:
    """Извлекает краткое описание Python-скрипта из sidecar-паспорта или docstring."""
    sidecar = filepath.parent / f"{filepath.stem}.passport.json"
    if sidecar.exists():
        try:
            with open(sidecar, "r", encoding="utf-8") as sf:
                sp_data = json.load(sf)
                desc = sp_data.get("description")
                if desc and desc.strip():
                    return desc.strip().split("\n")[0]
        except Exception:
            pass

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        module = ast.parse(content)
        doc = ast.get_docstring(module)
        if doc and doc.strip():
            return doc.strip().split("\n")[0]

        lines = content.split("\n")
        comments = []
        for line in lines:
            if line.strip().startswith("#") and not line.strip().startswith("#!"):
                cleaned = line.strip().lstrip("#").strip()
                if cleaned and not cleaned.startswith("-*-") and not cleaned.startswith("["):
                    comments.append(cleaned)
            elif line.strip():
                break
        if comments:
            return " ".join(comments[:2])
    except Exception:
        pass

    return "_Описание отсутствует_"


def extract_ps1_doc(filepath: Path) -> str:
    """Извлекает краткое описание PowerShell-скрипта из sidecar-паспорта или help-блока."""
    sidecar = filepath.parent / f"{filepath.stem}.passport.json"
    if sidecar.exists():
        try:
            with open(sidecar, "r", encoding="utf-8") as sf:
                sp_data = json.load(sf)
                desc = sp_data.get("description")
                if desc and desc.strip():
                    return desc.strip().split("\n")[0]
        except Exception:
            pass

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        match = re.search(r"<#\s*(.*?)\s*#>", content, re.DOTALL)
        if match:
            doc = match.group(1).strip()
            doc = re.sub(r"\.(SYNOPSIS|DESCRIPTION)", "", doc).strip()
            return doc.split("\n")[0]

        lines = content.split("\n")
        comments = []
        for line in lines:
            if line.strip().startswith("#"):
                cleaned = line.strip().lstrip("#").strip()
                if cleaned:
                    comments.append(cleaned)
            elif line.strip():
                break
        if comments:
            return " ".join(comments[:2])
    except Exception:
        pass

    return "_Описание отсутствует_"


def generate_catalog(target_dir: Path) -> Path:
    """Генерирует CATALOG.md для указанной директории."""
    catalog_file = target_dir / "CATALOG.md"
    documented_lines = [
        "## Оформленные скрипты",
        "",
        "| Имя файла | Тип | Описание |",
        "|---|---|---|",
    ]

    undocumented_lines = [
        "## Требуется описание",
        "> *Эти скрипты пока не имеют docstring или sidecar-паспорта.*",
        "",
        "| Имя файла | Тип |",
        "|---|---|",
    ]

    files = sorted(
        list(target_dir.rglob("*.py")) + list(target_dir.rglob("*.ps1")),
        key=lambda x: str(x.relative_to(target_dir)).lower()
    )
    has_undocumented = False

    for f in files:
        if f.name == "generate_catalog.py":
            continue

        rel_name = str(f.relative_to(target_dir)).replace("\\", "/")
        desc = "_Описание отсутствует_"
        type_str = ""

        if f.suffix == ".py":
            desc = extract_python_doc(f)
            type_str = "Python"
        elif f.suffix == ".ps1":
            desc = extract_ps1_doc(f)
            type_str = "PowerShell"
        else:
            continue

        if desc == "_Описание отсутствует_":
            has_undocumented = True
            undocumented_lines.append(f"| `{rel_name}` | {type_str} |")
        else:
            documented_lines.append(f"| `{rel_name}` | {type_str} | {desc} |")

    catalog_lines = [
        f"# Реестр скриптов {target_dir.name}/ (Script Registry)",
        "> *Этот файл генерируется автоматически скриптом `scripts/generate_catalog.py`*",
        "",
    ]

    if has_undocumented:
        catalog_lines.extend(undocumented_lines)
        catalog_lines.append("")

    catalog_lines.extend(documented_lines)
    catalog_lines.append("")

    with open(catalog_file, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(catalog_lines))

    return catalog_file


def main():
    parser = argparse.ArgumentParser(description="Генератор каталога скриптов CATALOG.md")
    parser.add_argument("--dir", "-d", help="Целевая директория для каталогизации (по умолчанию scripts/)")
    parser.add_argument("--all-standard", action="store_true", help="Сгенерировать каталоги для scripts, tools, projects/HOST_BUNDLE")
    args = parser.parse_args()

    if args.all_standard:
        dirs_to_process = [
            REPO_ROOT / "scripts",
            REPO_ROOT / "src",
        ]
        for d in dirs_to_process:
            if d.exists():
                cat = generate_catalog(d)
                print(f"Сгенерирован каталог: {cat}")
        return 0

    target = Path(args.dir).resolve() if args.dir else REPO_ROOT / "scripts"
    if not target.exists():
        print(f"Ошибка: Директория {target} не существует", file=sys.stderr)
        return 1

    catalog_path = generate_catalog(target)
    print(f"Каталог успешно сгенерирован: {catalog_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
