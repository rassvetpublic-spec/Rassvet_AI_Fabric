# -*- coding: utf-8 -*-
"""
tests.test_unified_supervisor - Комплексные тесты супервизора Antigravity и 3 механизмов авторизации.
Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.2) / Rassvet_AI_Fabric#13.
"""

from __future__ import annotations

import os
import time
import pytest
from pathlib import Path

from src.raif_ag_supervisor.unified_supervisor import (
    UnifiedSupervisor,
    BinaryPatchMechanism,
    AstraRoutingMechanism,
    CdpControllerMechanism,
    AntigravityProcessManager,
)


def test_binary_patch_lifecycle(tmp_path):
    """Тестирование цикла проверки и применения бинарного патча CP-31 без бэкапа."""
    bin_file = tmp_path / "mock_language_server.exe"
    mech = BinaryPatchMechanism()

    # Файл с оригинальной сигнатурой hasValidAuth
    prefix = b"\x90\x90\x90"
    suffix = b"\xCC\xCC\xCC"
    bin_file.write_bytes(prefix + mech.SIGNATURE_ORIGINAL + suffix)

    # 1. Probe до патча
    probe = mech.probe_binary(bin_file)
    assert probe["status"] == "UNPATCHED"
    assert probe["patchable"] is True
    assert probe["applied"] is False

    # 2. Применение патча
    res = mech.apply_patch_no_backup(bin_file)
    assert res["success"] is True
    assert res["status"] == "PATCHED"

    # 3. Probe после патча
    probe_after = mech.probe_binary(bin_file)
    assert probe_after["status"] == "ALREADY_PATCHED"
    assert probe_after["applied"] is True
    assert probe_after["patchable"] is False


def test_astra_routing_live_switch():
    """Тестирование мгновенной смены аккаунта сессии в RAM (ASTRA 8045/18045)."""
    router = AstraRoutingMechanism()
    
    # Биндинг к первому аккаунту
    res1 = router.bind_session("sess_alpha", "acc_google_01")
    assert res1["status"] == "BOUND"
    assert res1["requires_restart"] is False
    assert router.get_session_account("sess_alpha") == "acc_google_01"

    # Мгновенный rebind ко второму аккаунту без перезапуска
    res2 = router.bind_session("sess_alpha", "acc_google_02")
    assert res2["status"] == "BOUND"
    assert router.get_session_account("sess_alpha") == "acc_google_02"

    # Unbind
    assert router.unbind_session("sess_alpha") is True
    assert router.get_session_account("sess_alpha") is None


def test_cdp_controller_and_token_parsing(tmp_path):
    """Тестирование чтения DevToolsActivePort и парсинга 100% реальных токенов Gemini."""
    cdp = CdpControllerMechanism()
    
    # 1. Чтение порта
    port_file = tmp_path / "DevToolsActivePort"
    port_file.write_text("9222\n/devtools/browser/12345", encoding="utf-8")
    port = cdp.read_active_port(tmp_path)
    assert port == 9222

    # 2. Извлечение серверных токенов Gemini usageMetadata
    raw_payload = {
        "usageMetadata": {
            "promptTokenCount": 1542,
            "candidatesTokenCount": 384,
            "totalTokenCount": 1926,
            "cachedContentTokenCount": 512,
        }
    }
    tokens = cdp.parse_usage_metadata(raw_payload)
    assert tokens["prompt_tokens"] == 1542
    assert tokens["candidates_tokens"] == 384
    assert tokens["total_tokens"] == 1926
    assert tokens["cached_tokens"] == 512


def test_quota_alarm_detection():
    """Тестирование генерации аларма при низком остатке квоты (< 15%)."""
    supervisor = UnifiedSupervisor()
    quotas = {
        "acc_rich": 85.0,
        "acc_normal": 42.0,
        "acc_low": 8.5,
    }
    alarms = supervisor.check_quota_and_alarm(quotas, alarm_threshold_percent=15.0)
    assert len(alarms) == 1
    assert alarms[0]["alarm_type"] == "LOW_BALANCE_ALARM"
    assert alarms[0]["account_id"] == "acc_low"
    assert alarms[0]["remaining_percent"] == 8.5


def test_mechanism_benchmark_suite():
    """Тестирование сводного сравнительного бенчмарка 3 механизмов."""
    supervisor = UnifiedSupervisor()
    benchmarks = supervisor.run_mechanism_benchmark()
    assert len(benchmarks) == 3

    # Механизм 1 требует рестарта
    assert benchmarks[0].mechanism_id == "mech_01_binary_patch"
    assert benchmarks[0].requires_restart is True

    # Механизм 2 (ASTRA) - мгновенный rebind в RAM (< 1 мс)
    assert benchmarks[1].mechanism_id == "mech_02_astra_routing"
    assert benchmarks[1].requires_restart is False
    assert benchmarks[1].context_preserved is True

    # Механизм 3 (CDP) - официальные токены usageMetadata
    assert benchmarks[2].mechanism_id == "mech_03_cdp_controller"
    assert benchmarks[2].token_tracking_source == "CDP_OFFICIAL_GEMINI_USAGE_METADATA"
