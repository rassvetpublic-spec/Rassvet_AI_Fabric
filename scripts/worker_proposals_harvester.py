# -*- coding: utf-8 -*-
r"""
scripts.worker_proposals_harvester - Автоматический харвестер предложений независимых воркеров.
Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / SENIOR_ARCHITECTURE_STANDARD_V6.0.

Функции:
1. Сканирование транскриптов субагентов (brain/**/transcript.jsonl) в директории сессии Antigravity.
2. Извлечение, семантическая дедупликация и ABCxXYZ классификация предложений воркеров.
3. Расчет метрик работы воркеров (total, implemented, backlog, rate).
4. Репликация сводного реестра во все приемники флота:
   - C:\_inbox (для Controller/ChatGPT и фоновых обработчиков)
   - C:\GIT\CONTROL_TOWER\control\registry\ (Башня 1 - SSOT)
   - C:\GIT\BPR40\memory\ (Башня 2 - Память)
   - C:\Gdrive_RassvetPublic\CONTROL_TOWER\control\registry\ (Башня 3 - Облако)
"""
from __future__ import annotations

__version__ = "1.0.0"

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BRAIN_ROOT = Path(r"C:\Users\alexa\.gemini\antigravity\brain")
DEFAULT_INBOX_DIR = Path(r"C:\\_inbox")
DEFAULT_CONTROL_TOWER_REGISTRY = Path(r"C:\GIT\CONTROL_TOWER\control\registry")
DEFAULT_BPR40_MEMORY = Path(r"C:\GIT\BPR40\memory")
DEFAULT_GDRIVE_REGISTRY = Path(r"C:\Gdrive_RassvetPublic\CONTROL_TOWER\control\registry")


def discover_subagent_transcripts(brain_root: Path = DEFAULT_BRAIN_ROOT) -> List[Tuple[str, Path]]:
    """Находит все файлы transcript.jsonl в поддиректориях brain."""
    if not brain_root.exists():
        return []
    transcripts: List[Tuple[str, Path]] = []
    for item in brain_root.iterdir():
        if item.is_dir():
            t_path = item / ".system_generated" / "logs" / "transcript.jsonl"
            if t_path.exists():
                transcripts.append((item.name, t_path))
    return transcripts


def extract_proposals_from_text(text: str, source_id: str) -> List[Dict[str, Any]]:
    """Извлекает структурированные предложения из текста транскрипта."""
    results: List[Dict[str, Any]] = []
    lines = text.split("\n")
    for line in lines:
        line_clean = line.strip()
        if not line_clean or len(line_clean) < 15:
            continue

        # Паттерн 1: [Класс A - X] Название: Описание
        match_class = re.search(r"\[(?:Класс|Class)\s*([ABC])\s*[-–—xX×]\s*([XYZ])\]\s*(.+)", line_clean, re.IGNORECASE)
        if match_class:
            class_val = match_class.group(1).upper()
            uncert_val = match_class.group(2).upper()
            content = match_class.group(3).strip()
            results.append({
                "class": f"Класс {class_val} - {uncert_val}",
                "class_letter": class_val,
                "uncert_letter": uncert_val,
                "content": content,
                "source_worker": source_id[:8],
                "raw": line_clean
            })
            continue

        # Паттерн 2: Маркированные предложения воркеров
        if any(marker in line_clean for marker in ["Предложение воркера:", "Proposal:", "Горизонт [Класс"]):
            results.append({
                "class": "Класс B - X",
                "class_letter": "B",
                "uncert_letter": "X",
                "content": line_clean,
                "source_worker": source_id[:8],
                "raw": line_clean
            })

    return results


def harvest_worker_proposals(
    brain_root: Path = DEFAULT_BRAIN_ROOT,
    max_days: int = 7
) -> Dict[str, Any]:
    """Сбор и структурирование всех предложений воркеров."""
    transcripts = discover_subagent_transcripts(brain_root)
    all_raw: List[Dict[str, Any]] = []

    for sub_id, t_path in transcripts:
        try:
            mtime = datetime.datetime.fromtimestamp(t_path.stat().st_mtime, tz=datetime.timezone.utc)
            now = datetime.datetime.now(datetime.timezone.utc)
            if (now - mtime).days > max_days:
                continue

            with open(t_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        content = record.get("content", "") or ""
                        thinking = record.get("thinking", "") or ""
                        full_text = f"{content}\n{thinking}"
                        extracted = extract_proposals_from_text(full_text, sub_id)
                        all_raw.extend(extracted)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            continue

    # Семантическая дедупликация
    dedup_map: Dict[str, Dict[str, Any]] = {}
    for item in all_raw:
        # Нормализация ключа
        norm_key = re.sub(r"[^\w\s]", "", item["content"][:60].lower())
        norm_key = re.sub(r"\s+", " ", norm_key).strip()
        if norm_key and norm_key not in dedup_map:
            dedup_map[norm_key] = item

    unique_proposals = list(dedup_map.values())

    # Расчет метрик
    by_class: Dict[str, int] = {
        "Класс A - X": 0, "Класс A - Y": 0, "Класс A - Z": 0,
        "Класс B - X": 0, "Класс B - Y": 0, "Класс B - Z": 0,
        "Класс C - X": 0, "Класс C - Y": 0, "Класс C - Z": 0,
    }
    for p in unique_proposals:
        c = p.get("class", "Класс B - X")
        if c in by_class:
            by_class[c] += 1
        else:
            by_class[c] = 1

    return {
        "schema": "KAT9I_WORKER_PROPOSALS/1.0",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "transcripts_scanned": len(transcripts),
        "total_proposals": len(unique_proposals),
        "by_class": by_class,
        "proposals": unique_proposals,
    }


def render_proposals_markdown(data: Dict[str, Any]) -> str:
    """Генерирует форматированный Markdown отчет."""
    lines = [
        "# 📋 РЕЕСТР ПРЕДЛОЖЕНИЙ НЕЗАВИСИМЫХ ВОРКЕРОВ (WORKER PROPOSALS HARVEST)",
        f"> **Сгенерировано:** {data.get('timestamp')} | **Транскриптов проверено:** {data.get('transcripts_scanned')}",
        "",
        "## 📊 Сводка распределения (ABC × XYZ)",
        "| Класс | X (Тактический) | Y (Системный) | Z (Стратегический) |",
        "|---|:---:|:---:|:---:|",
    ]
    bc = data.get("by_class", {})
    lines.append(f"| **Класс A (Критический)** | {bc.get('Класс A - X', 0)} | {bc.get('Класс A - Y', 0)} | {bc.get('Класс A - Z', 0)} |")
    lines.append(f"| **Класс B (Эргономика)**  | {bc.get('Класс B - X', 0)} | {bc.get('Класс B - Y', 0)} | {bc.get('Класс B - Z', 0)} |")
    lines.append(f"| **Класс C (Эксперименты)**| {bc.get('Класс C - X', 0)} | {bc.get('Класс C - Y', 0)} | {bc.get('Класс C - Z', 0)} |")
    lines.extend([
        "",
        f"**Всего уникальных предложений воркеров:** {data.get('total_proposals', 0)}",
        "",
        "## 🛠️ Список предложений",
        "| № | Класс | Воркер | Суть предложения |",
        "|---|---|---|---|",
    ])
    for i, p in enumerate(data.get("proposals", []), 1):
        content = p.get("content", "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {i} | `{p.get('class')}` | `{p.get('source_worker')}` | {content} |")

    lines.append("")
    return "\n".join(lines)


def replicate_to_destinations(
    json_content: str,
    md_content: str,
    date_str: str
) -> Dict[str, str]:
    """Реплицирует отчет и json во все приемники флота."""
    results: Dict[str, str] = {}
    destinations = [
        (DEFAULT_INBOX_DIR, f"WORKER_PROPOSALS_{date_str}"),
        (DEFAULT_CONTROL_TOWER_REGISTRY, "WORKER_PROPOSALS_REGISTRY"),
        (DEFAULT_BPR40_MEMORY, "WORKER_PROPOSALS_REGISTRY"),
        (DEFAULT_GDRIVE_REGISTRY, "WORKER_PROPOSALS_REGISTRY"),
    ]

    for dest_dir, base_name in destinations:
        try:
            if not dest_dir.exists():
                dest_dir.mkdir(parents=True, exist_ok=True)
            json_file = dest_dir / f"{base_name}.json"
            md_file = dest_dir / f"{base_name}.md"

            json_file.write_text(json_content, encoding="utf-8", newline="\n")
            md_file.write_text(md_content, encoding="utf-8", newline="\n")

            # Для C:\_inbox также создаем стабильную неканоническую копию без даты
            if dest_dir == DEFAULT_INBOX_DIR:
                (dest_dir / "WORKER_PROPOSALS_REGISTRY.json").write_text(json_content, encoding="utf-8", newline="\n")
                (dest_dir / "WORKER_PROPOSALS_REGISTRY.md").write_text(md_content, encoding="utf-8", newline="\n")

            sha = hashlib.sha256(json_file.read_bytes()).hexdigest()[:16]
            results[str(dest_dir)] = f"PASS ({sha})"
        except Exception as exc:
            results[str(dest_dir)] = f"FAIL ({exc})"

    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Автоматический сбор и репликация предложений воркеров.")
    parser.add_argument("--brain-root", type=Path, default=DEFAULT_BRAIN_ROOT, help="Путь к папке brain")
    parser.add_argument("--days", type=int, default=7, help="Количество дней для сканирования")
    parser.add_argument("--json", action="store_true", help="Вывести результат в формате JSON")
    parser.add_argument("--replicate", action="store_true", help="Реплицировать в C:\\_inbox и Три Башни")
    args = parser.parse_args(argv)

    data = harvest_worker_proposals(brain_root=args.brain_root, max_days=args.days)
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    md_str = render_proposals_markdown(data)

    if args.replicate:
        date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        rep_status = replicate_to_destinations(json_str, md_str, date_str)
        data["replication"] = rep_status

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(md_str)
        if args.replicate:
            print("\n📡 Статус репликации в приемники флота:")
            for k, v in data.get("replication", {}).items():
                print(f"  • {k} -> {v}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
