import unittest

from raif_ag_supervisor.verification import (
    SessionEvidence, SwitchVerdict, evaluate_handoff,
)


class SwitchVerificationTests(unittest.TestCase):
    def source(self, **changes):
        base = dict(
            server_pid=123, server_start_marker="synthetic-start-1",
            account_handle="raif-" + "a" * 32, identity_verified=True,
            stream_continuity_verified=False,
        )
        base.update(changes)
        return SessionEvidence(**base)

    def target(self, **changes):
        base = dict(
            server_pid=123, server_start_marker="synthetic-start-1",
            account_handle="raif-" + "b" * 32, identity_verified=True,
            stream_continuity_verified=True,
        )
        base.update(changes)
        return SessionEvidence(**base)

    def test_complete_synthetic_evidence_is_verified(self):
        verdict = evaluate_handoff(self.source(), self.target(), "raif-" + "b" * 32)
        self.assertEqual(verdict.verdict, SwitchVerdict.VERIFIED)

    def test_same_pid_but_restarted_instance_is_not_verified(self):
        verdict = evaluate_handoff(
            self.source(), self.target(server_start_marker="synthetic-start-2"),
            "raif-" + "b" * 32,
        )
        self.assertEqual(verdict.verdict, SwitchVerdict.PROCESS_RESTARTED)

    def test_credential_only_change_has_no_identity_proof(self):
        verdict = evaluate_handoff(
            self.source(), self.target(identity_verified=False), "raif-" + "b" * 32
        )
        self.assertEqual(verdict.verdict, SwitchVerdict.INCONCLUSIVE)

    def test_account_switched_but_stream_not_proven(self):
        verdict = evaluate_handoff(
            self.source(), self.target(stream_continuity_verified=False),
            "raif-" + "b" * 32,
        )
        self.assertEqual(verdict.verdict, SwitchVerdict.ACCOUNT_CHANGED)

    def test_unchanged_account_fails(self):
        verdict = evaluate_handoff(
            self.source(), self.source(), "raif-" + "b" * 32
        )
        self.assertEqual(verdict.verdict, SwitchVerdict.ACCOUNT_UNCHANGED)

    def test_unexpected_account_fails(self):
        verdict = evaluate_handoff(
            self.source(), self.target(), "raif-" + "c" * 32
        )
        self.assertEqual(verdict.verdict, SwitchVerdict.WRONG_ACCOUNT)

    def test_missing_process_instance_is_inconclusive(self):
        verdict = evaluate_handoff(
            self.source(), self.target(server_pid=None), "raif-" + "b" * 32
        )
        self.assertEqual(verdict.verdict, SwitchVerdict.INCONCLUSIVE)

    def test_evidence_and_result_reprs_do_not_expose_account_handle(self):
        target = "raif-" + "b" * 32
        evidence = self.target()
        verdict = evaluate_handoff(self.source(), evidence, target)
        self.assertNotIn(target, repr(evidence))
        self.assertNotIn(target, repr(verdict))


if __name__ == "__main__":
    unittest.main()
