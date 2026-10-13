# -*- coding: utf-8 -*-
"""
src.raif_ag_supervisor.hot_switcher - Высокоуровневый координатор горячей смены аккаунтов Antigravity.
Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / MTD 011011.
"""
from __future__ import annotations

__version__ = "1.0.0"

import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

from .session_adapter import StandaloneSessionAdapter, SwitchResult
from .token_refresh import load_cached_profiles, FormattedAccountCredential, mask_email


@dataclass(frozen=True)
class HotSwitchReport:
    success: bool
    status: str
    target_account_id: str
    target_email_masked: str
    old_pid: Optional[int]
    new_pid: Optional[int]
    duration_ms: float
    rolled_back: bool
    details: str

    def safe_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "target_account_id": self.target_account_id,
            "target_email_masked": self.target_email_masked,
            "old_pid": self.old_pid,
            "new_pid": self.new_pid,
            "duration_ms": round(self.duration_ms, 2),
            "rolled_back": self.rolled_back,
            "details": self.details,
        }


class HotSwitcher:
    """Координатор горячей смены профилей с контролем свежести и резервным копированием."""

    def __init__(self, adapter: Optional[StandaloneSessionAdapter] = None) -> None:
        self.adapter = adapter or StandaloneSessionAdapter()

    def list_candidate_profiles(self) -> List[FormattedAccountCredential]:
        """Возвращает список доступных профилей, отсортированных по свежести."""
        profiles = load_cached_profiles()
        return [p for p in profiles if p.has_fresh_access]

    def switch_to_candidate(
        self,
        candidate_index: int = 0,
        timeout_seconds: float = 6.0,
    ) -> HotSwitchReport:
        """Выполняет переключение на указанный профиль кандидата."""
        candidates = self.list_candidate_profiles()
        if not candidates:
            return HotSwitchReport(
                success=False,
                status="NO_FRESH_CANDIDATES",
                target_account_id="",
                target_email_masked="",
                old_pid=None,
                new_pid=None,
                duration_ms=0.0,
                rolled_back=False,
                details="No cached accounts with fresh access token found (expiry > 120s)",
            )

        if candidate_index < 0 or candidate_index >= len(candidates):
            candidate_index = 0

        target = candidates[candidate_index]

        # Создаем резервный снапшот на диске перед запуском
        backup_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "RAiF" / "AGSupervisor" / "rollback"
        backup_dir.mkdir(parents=True, exist_ok=True)
        raw_native = self.adapter.read_native_credential_bytes()
        if raw_native:
            backup_file = backup_dir / f"pre-switch-{int(time.time())}.raw"
            backup_file.write_bytes(raw_native)

        # Запуск нативного переключения
        res = self.adapter.execute_hot_switch(
            new_credential=target.payload,
            timeout_seconds=timeout_seconds,
        )

        return HotSwitchReport(
            success=(res.status == "SUCCESS"),
            status=res.status,
            target_account_id=target.account_id,
            target_email_masked=target.email_masked,
            old_pid=res.old_pid,
            new_pid=res.new_pid,
            duration_ms=res.duration_ms,
            rolled_back=res.rolled_back,
            details=res.details,
        )
