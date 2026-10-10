"""CP-54C1 offline synthetic-only tests; zero real account identity reads."""
import json
import unittest

from raif_ag_supervisor.session_evidence import (
    ProcessStamp, process_relation, bounded_session_evidence,
)


class SessionEvidenceTests(unittest.TestCase):
    def test_same_instance_never_proves_account(self):
        first = ProcessStamp(1234, "01dc000000000001")
        evidence = bounded_session_evidence(first, first,
            {"email": "secret@example.test", "token": "DONOTLEAK"})
        self.assertEqual(evidence["process_relation"], "SAME_PROCESS_INSTANCE")
        self.assertFalse(evidence["account_identity_verified"])
        self.assertFalse(evidence["eligible_for_pool"])
        self.assertNotIn("secret@example.test", json.dumps(evidence))
        self.assertNotIn("DONOTLEAK", json.dumps(evidence))

    def test_pid_reused_does_not_count_as_same_instance(self):
        first = ProcessStamp(1234, "01dc000000000001")
        next_process = ProcessStamp(1234, "01dc000000000002")
        self.assertEqual(process_relation(first, next_process), "PROCESS_INSTANCE_CHANGED")

    def test_pid_changed(self):
        self.assertEqual(process_relation(ProcessStamp(1,"0000000000000001"),
              ProcessStamp(2,"0000000000000001")), "PROCESS_INSTANCE_CHANGED")

    def test_none_is_unknown(self):
        self.assertEqual(process_relation(None, None), "PROCESS_UNVERIFIED")
        self.assertEqual(bounded_session_evidence(None, None)["active_account_identity"],
                         "IDENTITY_UNVERIFIED")

    def test_invalid_pids(self):
        for pid in (False, 0, -1, 2**32, "1234", 1.5):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                ProcessStamp(pid, "0000000000000001")

    def test_invalid_filetime(self):
        for stamp in ("", "0"*16, "ABCDEF0000000001", "a"*15, "f"*17, None):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                ProcessStamp(2222, stamp)

    def test_mutable_attestation_cannot_override(self):
        report = bounded_session_evidence(None, None, {
            "identity_verified":True,"quota": 1.0,"hasValidAuth":True,
            "account_id": "raif-"+"f"*32,
        })
        self.assertFalse(report["account_identity_verified"])
        self.assertFalse(report["hot_swap_verified"])
        self.assertFalse(report["stream_continuity_verified"])


if __name__ == "__main__":
    unittest.main()
