# -*- coding: utf-8 -*-
"""
tests.test_hot_switcher - Тесты для HotSwitcher координатора.
Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / MTD 011011.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from raif_ag_supervisor.hot_switcher import HotSwitcher, HotSwitchReport
from raif_ag_supervisor.session_adapter import SwitchResult
from raif_ag_supervisor.token_refresh import FormattedAccountCredential


class TestHotSwitcher(unittest.TestCase):
    def test_switch_no_candidates(self):
        switcher = HotSwitcher()
        with patch.object(switcher, "list_candidate_profiles", return_value=[]):
            rep = switcher.switch_to_candidate()
            self.assertFalse(rep.success)
            self.assertEqual(rep.status, "NO_FRESH_CANDIDATES")

    def test_switch_success_flow(self):
        mock_adapter = MagicMock()
        mock_adapter.read_native_credential_bytes.return_value = b'{"token":{}}'
        mock_adapter.execute_hot_switch.return_value = SwitchResult(
            status="SUCCESS",
            target="gemini:antigravity",
            old_pid=1234,
            new_pid=5678,
            duration_ms=1750.0,
            rolled_back=False,
            details="Child language_server respawned (PID 1234 -> 5678) in 1750.0ms",
        )

        dummy_cand = FormattedAccountCredential(
            account_id="acc-01",
            email_masked="t***t@gmail.com",
            has_fresh_access=True,
            expires_in_seconds=1500.0,
            payload={"token": {"access_token": "abc"}},
        )

        switcher = HotSwitcher(adapter=mock_adapter)
        with patch.object(switcher, "list_candidate_profiles", return_value=[dummy_cand]):
            rep = switcher.switch_to_candidate(0)
            self.assertTrue(rep.success)
            self.assertEqual(rep.status, "SUCCESS")
            self.assertEqual(rep.old_pid, 1234)
            self.assertEqual(rep.new_pid, 5678)
            self.assertEqual(rep.duration_ms, 1750.0)


if __name__ == "__main__":
    unittest.main()
