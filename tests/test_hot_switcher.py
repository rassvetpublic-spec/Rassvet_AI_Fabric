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

    def test_switch_to_account_index_success(self):
        mock_adapter = MagicMock()
        mock_adapter.read_native_credential_bytes.return_value = b'{"token":{}}'
        mock_adapter.execute_hot_switch.return_value = SwitchResult(
            status="SUCCESS",
            target="gemini:antigravity",
            old_pid=2001,
            new_pid=3002,
            duration_ms=1200.0,
            rolled_back=False,
            details="Child language_server respawned in 1200.0ms",
        )
        dummy_prof = FormattedAccountCredential(
            account_id="acc-target",
            email_masked="u***r@gmail.com",
            has_fresh_access=False,
            expires_in_seconds=-500.0,
            payload={"token": {"access_token": "xyz"}},
        )
        switcher = HotSwitcher(adapter=mock_adapter)
        with patch.object(switcher, "get_all_profiles", return_value=[dummy_prof]):
            rep = switcher.switch_to_account_index(0)
            self.assertTrue(rep.success)
            self.assertEqual(rep.status, "SUCCESS")
            self.assertEqual(rep.target_account_id, "acc-target")
            self.assertEqual(rep.new_pid, 3002)

    def test_switch_to_account_index_out_of_bounds(self):
        switcher = HotSwitcher()
        dummy_prof = FormattedAccountCredential(
            account_id="acc-0",
            email_masked="a***b@gmail.com",
            has_fresh_access=True,
            expires_in_seconds=3600.0,
            payload={"token": {}},
        )
        with patch.object(switcher, "get_all_profiles", return_value=[dummy_prof]):
            rep = switcher.switch_to_account_index(99)
            self.assertFalse(rep.success)
            self.assertEqual(rep.status, "INDEX_OUT_OF_BOUNDS")

    def test_switch_to_account_id(self):
        mock_adapter = MagicMock()
        mock_adapter.read_native_credential_bytes.return_value = b'{"token":{}}'
        mock_adapter.execute_hot_switch.return_value = SwitchResult(
            status="SUCCESS",
            target="gemini:antigravity",
            old_pid=100,
            new_pid=200,
            duration_ms=1000.0,
            rolled_back=False,
            details="Respawned",
        )
        p1 = FormattedAccountCredential(account_id="id-1", email_masked="a***1@gmail.com", has_fresh_access=False, expires_in_seconds=0, payload={})
        p2 = FormattedAccountCredential(account_id="id-2", email_masked="a***2@gmail.com", has_fresh_access=False, expires_in_seconds=0, payload={})
        switcher = HotSwitcher(adapter=mock_adapter)
        with patch.object(switcher, "get_all_profiles", return_value=[p1, p2]):
            rep = switcher.switch_to_account_id("id-2")
            self.assertTrue(rep.success)
            self.assertEqual(rep.target_account_id, "id-2")

            rep_missing = switcher.switch_to_account_id("non-existent")
            self.assertFalse(rep_missing.success)
            self.assertEqual(rep_missing.status, "ACCOUNT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
