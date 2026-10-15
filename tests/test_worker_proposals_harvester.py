# -*- coding: utf-8 -*-
"""
Тесты для scripts/worker_proposals_harvester.py
"""
import json
import pytest
from pathlib import Path
from scripts.worker_proposals_harvester import (
    discover_subagent_transcripts,
    extract_proposals_from_text,
    render_proposals_markdown,
    replicate_to_destinations,
)


def test_extract_proposals_class_format():
    text = """
    Некоторый отладочный вывод
    [Класс A - X] Автоматический сбор истории коммитов в единый JSONL-лог: Фоновый сборщик
    Промежуточный шаг
    [Класс B - Y] Интеграция реестра брошенных решений с GitHub Issues Archive: Синхронизация
    """
    proposals = extract_proposals_from_text(text, "subagent_12345")
    assert len(proposals) == 2
    assert proposals[0]["class"] == "Класс A - X"
    assert proposals[0]["source_worker"] == "subagent"
    assert "Автоматический сбор истории" in proposals[0]["content"]
    assert proposals[1]["class"] == "Класс B - Y"


def test_extract_proposals_empty():
    text = "Просто обычный лог без предложений и горизонтов"
    proposals = extract_proposals_from_text(text, "worker_1")
    assert len(proposals) == 0


def test_render_proposals_markdown():
    mock_data = {
        "timestamp": "2026-10-15T02:00:00Z",
        "transcripts_scanned": 5,
        "total_proposals": 2,
        "by_class": {
            "Класс A - X": 1,
            "Класс B - Y": 1,
        },
        "proposals": [
            {
                "class": "Класс A - X",
                "source_worker": "wrk_1",
                "content": "Критическая оптимизация"
            },
            {
                "class": "Класс B - Y",
                "source_worker": "wrk_2",
                "content": "Улучшение интерфейса"
            }
        ]
    }
    md = render_proposals_markdown(mock_data)
    assert "РЕЕСТР ПРЕДЛОЖЕНИЙ НЕЗАВИСИМЫХ ВОРКЕРОВ" in md
    assert "Критическая оптимизация" in md
    assert "Улучшение интерфейса" in md


def test_replicate_to_destinations(tmp_path):
    json_data = json.dumps({"test": 123})
    md_data = "# Test"
    
    # Мокаем пути
    target_dir = tmp_path / "inbox"
    from scripts import worker_proposals_harvester
    old_inbox = worker_proposals_harvester.DEFAULT_INBOX_DIR
    old_ct = worker_proposals_harvester.DEFAULT_CONTROL_TOWER_REGISTRY
    old_bpr40 = worker_proposals_harvester.DEFAULT_BPR40_MEMORY
    old_gdrive = worker_proposals_harvester.DEFAULT_GDRIVE_REGISTRY

    try:
        worker_proposals_harvester.DEFAULT_INBOX_DIR = tmp_path / "inbox"
        worker_proposals_harvester.DEFAULT_CONTROL_TOWER_REGISTRY = tmp_path / "ct"
        worker_proposals_harvester.DEFAULT_BPR40_MEMORY = tmp_path / "bpr40"
        worker_proposals_harvester.DEFAULT_GDRIVE_REGISTRY = tmp_path / "gdrive"

        status = replicate_to_destinations(json_data, md_data, "20261015")
        assert len(status) == 4
        for k, v in status.items():
            assert "PASS" in v

        # Проверим физическое наличие файлов
        assert (tmp_path / "inbox" / "WORKER_PROPOSALS_20261015.json").exists()
        assert (tmp_path / "inbox" / "WORKER_PROPOSALS_20261015.md").exists()
    finally:
        worker_proposals_harvester.DEFAULT_INBOX_DIR = old_inbox
        worker_proposals_harvester.DEFAULT_CONTROL_TOWER_REGISTRY = old_ct
        worker_proposals_harvester.DEFAULT_BPR40_MEMORY = old_bpr40
        worker_proposals_harvester.DEFAULT_GDRIVE_REGISTRY = old_gdrive
