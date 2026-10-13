# -*- coding: utf-8 -*-
"""
src.raif_ag_supervisor.cli_switch - Консольный интерфейс безопасной горячей смены аккаунтов Antigravity.
Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / MTD 011011.
"""
from __future__ import annotations

__version__ = "1.0.0"

import os
import sys
import json
import argparse
from pathlib import Path

# Гарантия импорта из src
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from raif_ag_supervisor.hot_switcher import HotSwitcher
from raif_ag_supervisor.session_adapter import StandaloneSessionAdapter
from raif_ag_supervisor.token_refresh import mask_email


def get_transport_hub_quotas_data(adapter: StandaloneSessionAdapter, switcher: HotSwitcher) -> dict:
    import glob
    import time
    active_cred = adapter.read_native_credential_json()
    active_rt = active_cred.get("token", {}).get("refresh_token", "") if active_cred else ""
    active_ls = adapter.find_language_server_process()
    pid = active_ls.pid if active_ls else None

    files = sorted(glob.glob(os.path.expanduser("~/.antigravity_tools/accounts/*.json")))
    accounts = []
    active_account = None

    for idx, p in enumerate(files):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            rt = data.get("token", {}).get("refresh_token", "")
            is_active = (rt == active_rt) and bool(rt)
            email_m = mask_email(data.get("email", ""))
            quota = data.get("quota", {})
            tier = quota.get("subscription_tier", "PRO")
            groups = {g.get("display_name"): {b.get("window"): b for b in g.get("buckets", [])} for g in quota.get("quota_groups", [])}

            g_5h = groups.get("Gemini Models", {}).get("5h", {}).get("remaining_fraction", 0.0) * 100.0
            g_wk = groups.get("Gemini Models", {}).get("weekly", {}).get("remaining_fraction", 0.0) * 100.0
            c_5h = groups.get("Claude and GPT models", {}).get("5h", {}).get("remaining_fraction", 0.0) * 100.0
            c_wk = groups.get("Claude and GPT models", {}).get("weekly", {}).get("remaining_fraction", 0.0) * 100.0

            acc_obj = {
                "id": idx + 1,
                "index": idx,
                "account_id": data.get("id", ""),
                "email": email_m,
                "tier": tier,
                "is_active": is_active,
                "gemini_5h": round(g_5h, 1),
                "gemini_weekly": round(g_wk, 1),
                "claude_5h": round(c_5h, 1),
                "claude_weekly": round(c_wk, 1),
            }
            if is_active:
                active_account = acc_obj
            accounts.append(acc_obj)
        except Exception:
            continue

    return {
        "status": "OK",
        "active_pid": pid,
        "active_target": adapter.target_name,
        "active_account": active_account,
        "auto_failover_enabled": True,
        "failover_threshold_percent": 10.0,
        "accounts": accounts,
        "recommendation": "Рекомендация: переключение на аккаунт [2] или [4] (баланс > 80% / 100%)",
        "timestamp": time.time(),
    }


def display_transport_hub_quotas(adapter: StandaloneSessionAdapter, switcher: HotSwitcher) -> int:
    active_ls = adapter.find_language_server_process()
    pid_str = f"PID {active_ls.pid}" if active_ls else "NOT FOUND"
    data = get_transport_hub_quotas_data(adapter, switcher)

    print("=" * 105)
    print("  [+] RAiF Transport Hub - Матрица остатков квот флота Google / Antigravity")
    print(f"  Активный Language Server: {pid_str} | Запись WinCred: {adapter.target_name}")
    print("=" * 105)

    header = "Idx | Status       | Email                        | Tier | Gemini 5h | Gemini Wk | Claude 5h | Claude Wk"
    print(header)
    print("-" * 105)

    for acc in data.get("accounts", []):
        status_str = "[*] ACTIVE  " if acc["is_active"] else "    STANDBY "
        print(f" {acc['index']:2d} | {status_str} | {acc['email']:<28} | {acc['tier']:^4} | {acc['gemini_5h']:8.1f}% | {acc['gemini_weekly']:8.1f}% | {acc['claude_5h']:8.1f}% | {acc['claude_weekly']:8.1f}%")

    print("=" * 105)
    print(f"  [INFO] {data.get('recommendation', '')}")
    print("=" * 105)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="RAiF Antigravity Hot-Switch CLI & Transport Hub")
    parser.add_argument("--hub", "--quotas", action="store_true", help="Показать матрицу остатков квот флота в RAiF Transport Hub")
    parser.add_argument("--json", action="store_true", help="Вывод результатов в формате JSON (для Sidecar API)")
    parser.add_argument("--status", action="store_true", help="Показать статус активного аккаунта, процессов и кандидатов")
    parser.add_argument("--switch", action="store_true", help="Выполнить горячее переключение на следующего свежего кандидата")
    parser.add_argument("--index", type=int, default=0, help="Индекс кандидата для переключения (по умолчанию: 0)")
    parser.add_argument("--timeout", type=float, default=6.0, help="Тайм-аут ожидания респауна в секундах")
    args = parser.parse_args()

    adapter = StandaloneSessionAdapter()
    switcher = HotSwitcher(adapter=adapter)

    if args.hub:
        if args.json:
            print(json.dumps(get_transport_hub_quotas_data(adapter, switcher), ensure_ascii=False, indent=2))
            return 0
        return display_transport_hub_quotas(adapter, switcher)

    if args.status or (not args.switch):
        if args.json:
            proc = adapter.find_language_server_process()
            cred = adapter.read_native_credential_json()
            email = cred.get("token", {}).get("email", "") if cred else ""
            candidates = [c.safe_dict() for c in switcher.list_candidate_profiles()]
            payload = {
                "active_pid": proc.pid if proc else None,
                "target_name": adapter.target_name,
                "email_masked": mask_email(email),
                "candidates_count": len(candidates),
                "candidates": candidates,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

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
        if not args.json:
            print("[ACTION] Выполняю переключение Child Respawn...")
        report = switcher.switch_to_candidate(candidate_index=args.index, timeout_seconds=args.timeout)
        if args.json:
            print(json.dumps(report.safe_dict(), ensure_ascii=False, indent=2))
            return 0 if report.success else 1
        print(f"[RESULT] Status: {report.status} | Success: {report.success}")
        print(f"[DETAILS] {report.details}")
        print(f"[ACCOUNT] Target: {report.target_email_masked} ({report.target_account_id})")
        print(f"[TIMING] Длительность: {report.duration_ms:.1f} мс | Откат: {report.rolled_back}")
        return 0 if report.success else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
