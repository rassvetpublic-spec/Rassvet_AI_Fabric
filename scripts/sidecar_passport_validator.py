# -*- coding: utf-8 -*-
"""
📋 Валидатор и гейт-контроллер Sidecar-паспортов по канону Архитектора (Sidecar Passports Gate).
Проверяет наличие в коде только __version__, наличие строго рядом файла <name>.passport.json,
соответствие версии в JSON и коде, а также валидность схемы контракта.
"""
from __future__ import annotations

__version__ = "1.1.0"

import ast
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class SidecarPassportValidator:
    """Валидатор канонических Sidecar-паспортов модулей."""

    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = repo_root or REPO_ROOT

    def extract_code_version(self, py_path: Path) -> Tuple[Optional[str], bool]:
        """Извлекает __version__ из AST и проверяет отсутствие устаревшего inline __passport__."""
        if not py_path.exists():
            return None, False
        try:
            with open(py_path, "r", encoding="utf-8", errors="replace") as f:
                tree = ast.parse(f.read(), filename=str(py_path))
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

    def validate_module(self, py_path_str: str) -> Dict[str, Any]:
        """Проводит полную валидацию связки код + sidecar JSON."""
        py_path = Path(py_path_str)
        violations: List[Dict[str, Any]] = []

        if not py_path.exists() or py_path.suffix != ".py":
            return {
                "file": str(py_path),
                "is_valid": False,
                "violations": [{"rule": "INVALID_FILE", "severity": "P0", "detail": "Файл не существует или не является .py"}]
            }

        stem = py_path.stem
        sidecar_path = py_path.parent / f"{stem}.passport.json"

        # 1. Извлечение __version__ из кода
        code_ver, has_inline = self.extract_code_version(py_path)
        if not code_ver:
            violations.append({
                "rule": "MISSING_CODE_VERSION",
                "severity": "P0",
                "detail": f"В файле '{py_path.name}' отсутствует обязательный __version__ = 'X.Y.Z'"
            })
        elif not SEMVER_PATTERN.match(code_ver):
            violations.append({
                "rule": "INVALID_SEMVER",
                "severity": "P0",
                "detail": f"Версия в коде '{code_ver}' не соответствует формату SemVer (X.Y.Z)"
            })

        if has_inline:
            violations.append({
                "rule": "DEPRECATED_INLINE_PASSPORT",
                "severity": "P1",
                "detail": "Встроенный словарь __passport__ в коде запрещён каноном Sidecar; паспорт должен лежать рядом в JSON"
            })

        # 2. Проверка наличия sidecar JSON строго рядом
        if not sidecar_path.exists():
            violations.append({
                "rule": "MISSING_SIDECAR_PASSPORT",
                "severity": "P0",
                "detail": f"Обязательный sidecar-паспорт '{sidecar_path.name}' не найден рядом с исполняемым файлом"
            })
            return {
                "file": str(py_path),
                "sidecar": str(sidecar_path),
                "is_valid": False,
                "violations": violations
            }

        # 3. Валидация содержимого sidecar JSON
        try:
            with open(sidecar_path, "r", encoding="utf-8") as f:
                passport_data = json.load(f)
        except Exception as e:
            violations.append({
                "rule": "INVALID_JSON_SYNTAX",
                "severity": "P0",
                "detail": f"Ошибка парсинга sidecar JSON: {e}"
            })
            return {
                "file": str(py_path),
                "sidecar": str(sidecar_path),
                "is_valid": False,
                "violations": violations
            }

        json_ver = passport_data.get("version")
        json_id = passport_data.get("module_id")

        if not json_ver:
            violations.append({
                "rule": "MISSING_VERSION_IN_PASSPORT",
                "severity": "P0",
                "detail": "Поле 'version' отсутствует в sidecar-паспорте"
            })
        elif code_ver and json_ver != code_ver:
            violations.append({
                "rule": "VERSION_MISMATCH",
                "severity": "P0",
                "detail": f"Несовпадение версий: в коде '{code_ver}', в sidecar JSON '{json_ver}'"
            })

        if not json_id:
            violations.append({
                "rule": "MISSING_MODULE_ID",
                "severity": "P1",
                "detail": "Поле 'module_id' отсутствует в sidecar-паспорте"
            })

        # 4. Валидация машинописного контракта функций (AST Introspection Gate)
        passport_functions = passport_data.get("functions")
        if passport_functions is not None and isinstance(passport_functions, dict):
            ast_functions = self.extract_functions_from_ast(py_path)
            for fn_name, fn_meta in passport_functions.items():
                if fn_name not in ast_functions:
                    violations.append({
                        "rule": "FUNCTION_NOT_FOUND",
                        "severity": "P1",
                        "detail": f"Функция '{fn_name}', описанная в sidecar-паспорте, не найдена в коде '{py_path.name}'"
                    })
                else:
                    expected_args = fn_meta.get("args")
                    actual_args = ast_functions[fn_name].get("args", [])
                    if expected_args is not None and expected_args != actual_args:
                        violations.append({
                            "rule": "CONTRACT_DRIFT",
                            "severity": "P0",
                            "detail": f"Рассинхрон аргументов функции '{fn_name}': в коде {actual_args}, в паспорте {expected_args}"
                        })

        has_p0 = any(v["severity"] == "P0" for v in violations)
        return {
            "file": str(py_path),
            "sidecar": str(sidecar_path),
            "is_valid": not has_p0,
            "violations": violations,
            "passport_summary": {
                "module_id": json_id,
                "version": json_ver,
                "layer": passport_data.get("layer") or passport_data.get("category"),
                "description": passport_data.get("description"),
                "functions_count": len(passport_functions) if isinstance(passport_functions, dict) else 0
            } if not has_p0 else None
        }

    def extract_functions_from_ast(self, py_path: Path) -> Dict[str, Dict[str, Any]]:
        """Извлекает публичные функции и методы классов из AST модуля."""
        if not py_path.exists():
            return {}
        try:
            with open(py_path, "r", encoding="utf-8", errors="replace") as f:
                tree = ast.parse(f.read(), filename=str(py_path))
        except Exception:
            return {}

        stem = py_path.stem
        functions: Dict[str, Dict[str, Any]] = {}

        def _process_func(node: Any, class_name: Optional[str] = None):
            fn_name = f"{class_name}.{node.name}" if class_name else node.name
            args_list: List[str] = []
            inputs_meta: Dict[str, Any] = {}

            pos_args = getattr(node.args, "posonlyargs", []) + node.args.args
            num_pos = len(pos_args)
            num_defaults = len(node.args.defaults)
            default_offset = num_pos - num_defaults

            for idx, a in enumerate(pos_args):
                if class_name and a.arg in ("self", "cls"):
                    continue
                args_list.append(a.arg)
                is_req = idx < default_offset
                default_repr = None
                if not is_req and idx >= default_offset:
                    try:
                        default_repr = ast.unparse(node.args.defaults[idx - default_offset])
                    except Exception:
                        default_repr = "..."
                type_repr = "Any"
                if a.annotation:
                    try:
                        type_repr = ast.unparse(a.annotation)
                    except Exception:
                        type_repr = "Any"
                inputs_meta[a.arg] = {
                    "type": type_repr,
                    "required": is_req,
                    "default": default_repr
                }

            for idx, a in enumerate(getattr(node.args, "kwonlyargs", [])):
                args_list.append(a.arg)
                kw_def = node.args.kw_defaults[idx] if idx < len(node.args.kw_defaults) else None
                is_req = kw_def is None
                default_repr = None
                if not is_req and kw_def is not None:
                    try:
                        default_repr = ast.unparse(kw_def)
                    except Exception:
                        default_repr = "..."
                type_repr = "Any"
                if a.annotation:
                    try:
                        type_repr = ast.unparse(a.annotation)
                    except Exception:
                        type_repr = "Any"
                inputs_meta[a.arg] = {
                    "type": type_repr,
                    "required": is_req,
                    "default": default_repr
                }

            ret_type = "Any"
            if node.returns:
                try:
                    ret_type = ast.unparse(node.returns)
                except Exception:
                    ret_type = "Any"

            doc = ast.get_docstring(node)
            first_line = doc.strip().split("\n")[0] if doc else f"Функция {fn_name}"

            functions[fn_name] = {
                "fn_id": f"{stem}.{fn_name}",
                "description": first_line,
                "args": args_list,
                "inputs": inputs_meta,
                "outputs": {
                    "return_type": ret_type
                },
                "invariants": [
                    "FAIL_CLOSED",
                    "DETERMINISTIC"
                ]
            }

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("__"):
                    _process_func(node)
            elif isinstance(node, ast.ClassDef):
                if not node.name.startswith("_"):
                    for m in node.body:
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if not m.name.startswith("_"):
                                _process_func(m, class_name=node.name)

        return functions

    def enrich_sidecar_with_functions(self, py_path_str: str) -> Optional[Path]:
        """Обогащает существующий sidecar-паспорт модулем AST-контрактами всех функций."""
        py_path = Path(py_path_str)
        if not py_path.exists() or py_path.suffix != ".py":
            return None

        stem = py_path.stem
        sidecar_path = py_path.parent / f"{stem}.passport.json"
        if not sidecar_path.exists():
            self.generate_sidecar_skeleton(py_path_str)

        try:
            with open(sidecar_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        ast_functions = self.extract_functions_from_ast(py_path)
        data["schema"] = "BPR40_SIDECAR_PASSPORT/1.1"
        data["functions"] = ast_functions

        with open(sidecar_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return sidecar_path

    def generate_sidecar_skeleton(self, py_path_str: str, default_desc: str = "") -> Optional[Path]:
        """Генерирует заготовку sidecar-паспорта для модуля, если он отсутствует."""
        py_path = Path(py_path_str)
        if not py_path.exists() or py_path.suffix != ".py":
            return None

        stem = py_path.stem
        sidecar_path = py_path.parent / f"{stem}.passport.json"
        if sidecar_path.exists():
            return sidecar_path

        code_ver, _ = self.extract_code_version(py_path)
        ver = code_ver if code_ver else "1.0.0"

        doc_desc = default_desc
        if not doc_desc:
            try:
                with open(py_path, "r", encoding="utf-8", errors="replace") as f:
                    tree = ast.parse(f.read())
                    m_doc = ast.get_docstring(tree)
                    if m_doc:
                        doc_desc = m_doc.strip().split("\n")[0]
            except Exception:
                pass

        ast_functions = self.extract_functions_from_ast(py_path)

        skeleton = {
            "schema": "BPR40_SIDECAR_PASSPORT/1.1",
            "module_id": stem,
            "name": stem.replace("_", " ").title(),
            "version": ver,
            "standard": "SENIOR_ARCHITECTURE_STANDARD_V6.0",
            "layer": "quality_gates" if "gate" in stem or "qa" in stem else ("core" if "core" in stem else "tools"),
            "description": doc_desc or f"Модуль {stem}",
            "author": "RAIF_DEVELOPER",
            "inputs": {},
            "outputs": {},
            "invariants": [
                "SIDECAR_CANON_ENFORCED",
                "IN_CODE_ONLY_VERSION",
                "FAIL_CLOSED"
            ],
            "functions": ast_functions
        }

        with open(sidecar_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(skeleton, f, indent=2, ensure_ascii=False)
        return sidecar_path


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="CI-валидатор и гейт-контроллер Sidecar-паспортов CONTROL_TOWER (Sidecar Passports Gate)"
    )
    parser.add_argument("target", help="Путь к .py файлу или директории со скриптами")
    parser.add_argument("--generate-skeletons", action="store_true", help="Автоматически создать отсутствующие sidecar-паспорта")
    parser.add_argument("--enrich-functions", action="store_true", help="Обогатить существующие sidecar-паспорта контрактами функций из AST")
    parser.add_argument("--repo-root", default=None, help="Корневая директория репозитория")

    args = parser.parse_args()
    root_path = Path(args.repo_root) if args.repo_root else REPO_ROOT
    validator = SidecarPassportValidator(repo_root=root_path)
    target = Path(args.target)

    if not target.is_absolute():
        target = root_path / target

    if args.generate_skeletons:
        if target.is_file():
            res = validator.generate_sidecar_skeleton(str(target))
            print(f"Паспорт создан: {res}")
        elif target.is_dir():
            for p in sorted(target.rglob("*.py")):
                res = validator.generate_sidecar_skeleton(str(p))
                if res:
                    print(f"Паспорт: {res.name}")
        return 0

    if getattr(args, "enrich_functions", False):
        if target.is_file():
            res = validator.enrich_sidecar_with_functions(str(target))
            print(f"Паспорт обогащен: {res}")
        elif target.is_dir():
            for p in sorted(target.rglob("*.py")):
                res = validator.enrich_sidecar_with_functions(str(p))
                if res:
                    print(f"Обогащен: {res.name}")
        return 0

    # Обычная валидация
    files_to_check = []
    if target.is_file():
        files_to_check.append(target)
    elif target.is_dir():
        files_to_check = sorted(target.rglob("*.py"))
    else:
        print(f"Ошибка: цель '{target}' не найдена", file=sys.stderr)
        return 2

    total_checked = 0
    total_valid = 0
    total_violations = 0

    for py_file in files_to_check:
        total_checked += 1
        res = validator.validate_module(str(py_file))
        if res["is_valid"]:
            total_valid += 1
        else:
            print(f"[FAIL] {py_file.relative_to(root_path)}:")
            for v in res["violations"]:
                total_violations += 1
                print(f"   [{v['severity']}] {v['rule']}: {v['detail']}")

    print("-" * 50)
    print(f"Всего проверено: {total_checked} модулей")
    print(f"Валидно: {total_valid} | Нарушений: {total_violations}")

    if total_violations > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
