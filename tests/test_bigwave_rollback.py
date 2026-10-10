"""Synthetic-only restore; no native credential access or account operations."""
import json
import unittest
from raif_ag_supervisor.rollback_harness import SyntheticFault, simulate_rollback


class RollbackTests(unittest.TestCase):
    def test_happy_path_is_only_synthetic(self):
        report = simulate_rollback()
        self.assertEqual(report.verdict, "SYNTHETIC_RESTORE_VERIFIED")
        self.assertTrue(report.original_restored)
        self.assertTrue(report.journal_preceded_write)
        self.assertEqual((report.candidate_writes, report.restore_attempts), (1, 1))
        self.assertFalse(report.real_rollback_verified)

    def test_fail_before_write(self):
        report = simulate_rollback(SyntheticFault.FAIL_BEFORE_WRITE)
        self.assertEqual(report.candidate_writes, 0)
        self.assertEqual(report.restore_attempts, 0)
        self.assertEqual(report.verdict, "NO_WRITE_SAFE_FAIL")

    def test_crash_after_write_is_not_autorestored(self):
        report = simulate_rollback(SyntheticFault.CRASH_AFTER_WRITE)
        self.assertEqual(report.verdict, "RECOVERY_REQUIRED")
        self.assertFalse(report.original_restored)
        self.assertEqual(report.restore_attempts, 0)

    def test_mismatch_restore(self):
        report = simulate_rollback(SyntheticFault.READBACK_MISMATCH)
        self.assertEqual(report.verdict, "SYNTHETIC_RESTORE_VERIFIED_AFTER_MISMATCH")
        self.assertTrue(report.original_restored)

    def test_failed_restore_not_claimed_pass(self):
        report = simulate_rollback(SyntheticFault.RESTORE_FAILURE)
        self.assertEqual(report.verdict, "MANUAL_RECOVERY_REQUIRED")
        self.assertFalse(report.original_restored)
        self.assertEqual(report.restore_attempts, 1)

    def test_reused_pid_blocks_before_write(self):
        report = simulate_rollback(SyntheticFault.PID_REUSED)
        self.assertEqual(report.verdict, "BLOCKED_STALE_PROCESS")
        self.assertEqual(report.candidate_writes, 0)

    def test_concurrent_operation_blocks_before_write(self):
        report = simulate_rollback(SyntheticFault.CONCURRENT_OPERATION)
        self.assertEqual(report.verdict, "BLOCKED_ONE_WRITER_GATE")
        self.assertEqual(report.candidate_writes, 0)

    def test_disallow_custom_payloads_or_faults(self):
        for item in ("none", None, 0, b"native-credential", True):
            with self.subTest(type=type(item).__name__), self.assertRaises(ValueError):
                simulate_rollback(item)

    def test_report_is_redacted_and_no_identity_claim(self):
        for fault in SyntheticFault:
            report = simulate_rollback(fault).safe_dict()
            self.assertFalse(report["live_credentials_read"])
            self.assertFalse(report["account_identity_verified"])
            self.assertFalse(report["real_rollback_verified"])
            self.assertNotIn("Bearer", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
