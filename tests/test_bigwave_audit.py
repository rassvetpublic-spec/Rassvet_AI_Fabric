"""Privacy contract tests for strict, small, fixed-schema redacted audit."""
import json
import unittest

from raif_ag_supervisor.audit import StageAudit


class AuditTests(unittest.TestCase):
    def test_sequences_and_jsonl(self):
        log = StageAudit()
        log.append("PREPARE", "START", "BEGIN")
        log.append("PREPARE", "PASS", "READY")
        self.assertEqual([x["sequence"] for x in log.events], [1,2])
        self.assertEqual([json.loads(x)["state"] for x in log.jsonl().splitlines()],
                         ["START", "PASS"])

    def test_receipt_is_aggregate_only(self):
        log = StageAudit()
        log.append("EXEC", "BLOCKED", "PERMISSION_UNKNOWN")
        r=log.receipt()
        self.assertEqual(r["blocked"], 1)
        self.assertFalse(r["secrets_exported"])
        self.assertFalse(r["identity_verified"])

    def test_error_message_is_not_accepted(self):
        log = StageAudit()
        for code in ("private@example.test", "INVALID BEARER", "CRASH\nTOKEN", "..", "X"*66, ""):
            with self.subTest(code=code), self.assertRaises(ValueError):
                log.append("EXEC", "BLOCKED", code)
        self.assertEqual(len(log.events), 0)

    def test_untrusted_stage_is_rejected(self):
        with self.assertRaises(ValueError):
            StageAudit().append("C:/Users/secret", "START", "BEGIN")

    def test_invalid_state(self):
        with self.assertRaises(ValueError):
            StageAudit().append("START", "SUCCESS_BECAUSE_SO", "BEGIN")

    def test_limit(self):
        audit=StageAudit()
        for i in range(256):
            audit.append("STAGE", "PASS", "OK")
        with self.assertRaises(ValueError):
            audit.append("STAGE", "PASS", "OK")
        self.assertEqual(len(audit.events), 256)


if __name__ == "__main__":
    unittest.main()
