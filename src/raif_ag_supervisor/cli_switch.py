# -*- coding: utf-8 -*-
"""
src.raif_ag_supervisor.cli_switch - Консольный интерфейс безопасной горячей смены аккаунтов Antigravity.
Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / MTD 011011.
"""
from __future__ import annotations

__version__ = "1.0.0"

import os
import sys
import argparse
from pathlib import Path

# Гарантия импорта из src
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from raif_ag_supervisor.hot_switcher import HotSwitcher
from raif_ag_supervisor.session_adapter import StandaloneSessionAdapter
from raif_ag_supervisor.token_refresh import mask_email


def main() -> int:
    parser = argparse.ArgumentParser(description="RAiF Antigravity Hot-Switch CLI")
    parser.add_argument("--status", action="store_true", help="Показать статус активного аккаунта, процессов и кандидатов")
    parser.add_argument("--switch", action="store_true", help="Выполнить горячее переключение на следующего свежего кандидата")
    parser.add_argument("--index", type=int, default=0, help="Индекс кандидата для переключения (по умолчанию: 0)")
    parser.add_argument("--timeout", type=float, default=6.0, help="Тайм-аут ожидания респауна в секундах")
    args = parser.parse_args()

    adapter = StandaloneSessionAdapter()
    switcher = HotSwitcher(adapter=adapter)

    if args.status or (not args.switch):
        print("=" * 60)
        print("  RAiF Antigravity Session & Hot-Switch Status")
        print("=" * 60)

        # 1. Активный LS процесс
        proc = adapter.find_language_server_process()
        if proc:
            print(f"[LS PROCESS] Active language_server.exe: PID {proc.pid}")
        else:
            print("[LS PROCESS] language_server.exe: NOT FOUND")

        # 2. Нативная запись в CredMan
        cred = adapter.read_native_credential_json()
        if cred:
            email = cred.get("token", {}).get("email", "")
            expiry = cred.get("token", {}).get("expiry", "unknown")
            print(f"[WIN_CRED] Target: {adapter.target_name} | User: {mask_email(email)} | Expiry: {expiry}")
        else:
            print(f"[WIN_CRED] Target: {adapter.target_name} NOT FOUND")

        # 3. Список кандидатов
        candidates = switcher.list_candidate_profiles()
        print(f"\n[CANDIDATES] Доступно свежих профилей: {len(candidates)}")
        for idx, cand in enumerate(candidates):
            ttl_min = cand.expires_in_seconds / 60.0
            print(f"  [{idx}] ID: {cand.account_id[:8]}... | Email: {cand.email_masked:<24} | TTL: {ttl_min:.1f} мин")

        print("=" * 60)
        return 0

    if args.switch:
        print("[ACTION] Выполняю переключение Child Respawn...")
        report = switcher.switch_to_candidate(candidate_index=args.index, timeout_seconds=args.timeout)
        print(f"[RESULT] Status: {report.status} | Success: {report.success}")
        print(f"[DETAILS] {report.details}")
        print(f"[ACCOUNT] Target: {report.target_email_masked} ({report.target_account_id})")
        print(f"[TIMING] Длительность: {report.duration_ms:.1f} мс | Откат: {report.rolled_back}")
        return 0 if report.success else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
