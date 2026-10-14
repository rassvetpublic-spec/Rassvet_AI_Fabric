# -*- coding: utf-8 -*-
"""
tests/test_auto_failover_watchdog.py - 100% offline-safe тесты для авто-ротации аккаунтов при квоте <10%.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from raif_ag_supervisor.cli_switch import check_and_auto_failover, main
from raif_ag_supervisor.hot_switcher import HotSwitchReport


class TestAutoFailoverWatchdog:
    def test_active_account_healthy_no_switch(self) -> None:
        mock_adapter = MagicMock()
        mock_switcher = MagicMock()

        mock_data = {
            "active_account": {"id": 1, "index": 0, "gemini_5h": 85.0, "gemini_weekly": 90.0},
            "accounts": [
                {"id": 1, "index": 0, "is_active": True, "gemini_5h": 85.0, "gemini_weekly": 90.0},
                {"id": 2, "index": 1, "is_active": False, "gemini_5h": 95.0, "gemini_weekly": 95.0},
            ],
        }

        with patch("raif_ag_supervisor.cli_switch.get_transport_hub_quotas_data", return_value=mock_data):
            res = check_and_auto_failover(mock_adapter, mock_switcher, threshold=10.0)

        assert res["status"] == "HEALTHY"
        assert res["switched"] is False
        assert "above threshold" in res["reason"]
        mock_switcher.switch_to_account_index.assert_not_called()

    def test_active_account_exhausted_triggers_switch_to_best_candidate(self) -> None:
        mock_adapter = MagicMock()
        mock_switcher = MagicMock()

        mock_data = {
            "active_account": {"id": 1, "index": 0, "gemini_5h": 4.5, "gemini_weekly": 15.0},
            "accounts": [
                {"id": 1, "index": 0, "is_active": True, "gemini_5h": 4.5, "gemini_weekly": 15.0},
                {"id": 2, "index": 1, "is_active": False, "gemini_5h": 50.0, "gemini_weekly": 70.0},
                {"id": 3, "index": 2, "is_active": False, "gemini_5h": 92.0, "gemini_weekly": 95.0},
            ],
        }

        mock_report = HotSwitchReport(
            success=True,
            status="SUCCESS",
            target_account_id="acc-3",
            target_email_masked="best@example.com",
            old_pid=1000,
            new_pid=2000,
            duration_ms=45.0,
            rolled_back=False,
            details="Child Respawn completed",
        )
        mock_switcher.switch_to_account_index.return_value = mock_report

        with patch("raif_ag_supervisor.cli_switch.get_transport_hub_quotas_data", return_value=mock_data):
            res = check_and_auto_failover(mock_adapter, mock_switcher, threshold=10.0)

        assert res["status"] == "SWITCHED"
        assert res["switched"] is True
        assert res["to_account"]["id"] == 3  # Best candidate with 92%
        mock_switcher.switch_to_account_index.assert_called_once_with(2)

    def test_all_accounts_exhausted_fallback_local_gpu(self) -> None:
        mock_adapter = MagicMock()
        mock_switcher = MagicMock()

        mock_data = {
            "active_account": {"id": 1, "index": 0, "gemini_5h": 2.0, "gemini_weekly": 5.0},
            "accounts": [
                {"id": 1, "index": 0, "is_active": True, "gemini_5h": 2.0, "gemini_weekly": 5.0},
                {"id": 2, "index": 1, "is_active": False, "gemini_5h": 3.0, "gemini_weekly": 4.0},
            ],
        }

        with patch("raif_ag_supervisor.cli_switch.get_transport_hub_quotas_data", return_value=mock_data):
            res = check_and_auto_failover(mock_adapter, mock_switcher, threshold=10.0)

        assert res["status"] == "ALL_EXHAUSTED"
        assert res["switched"] is False
        assert "local_gpu" in res["fallback_target"]
        mock_switcher.switch_to_account_index.assert_not_called()
