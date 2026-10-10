"""Pure synthetic pool tests: no OAuth, no network, no Antigravity process access."""
import json
import unittest

from raif_ag_supervisor.pool import (
    AccountPool, GroupQuota, HandoffPlan, ModelGroup, PoolError,
    QuotaStatus, QuotaWindow, synthetic_demo,
)


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.first = "raif-" + "a" * 32
        self.second = "raif-" + "b" * 32
        self.third = "raif-" + "c" * 32
        self.now = 1_234_567.0
        self.stored = {self.first, self.second, self.third}
        self.pool = AccountPool(
            (self.first, self.second, self.third),
            lambda h: h in self.stored,
        )

    def quota(self, five=.8, week=.6, age=0, reset=None, disabled=False):
        return GroupQuota(
            QuotaWindow(five, self.now-age, reset_at=reset, disabled=disabled),
            QuotaWindow(week, self.now-age),
        )

    def fire(self, group=ModelGroup.GEMINI):
        return self.pool.record_http_error(self.first, group, 429, self.now)

    def test_no_recommendation_without_429(self):
        self.pool.record_quota(self.second, ModelGroup.GEMINI, self.quota())
        self.assertIsNone(self.pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now))

    def test_429_selects_known_credential_and_quota(self):
        self.pool.record_quota(self.second, ModelGroup.GEMINI, self.quota())
        self.fire()
        plan = self.pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now)
        self.assertIsInstance(plan, HandoffPlan)
        self.assertEqual(plan.target_handle, self.second)
        self.assertTrue(plan.requires_live_session_validation)
        self.assertFalse(plan.safe_summary()["account_switched"])

    def test_best_minimum_quota_wins(self):
        self.pool.record_quota(self.second, ModelGroup.GEMINI, self.quota(five=.9, week=.2))
        self.pool.record_quota(self.third, ModelGroup.GEMINI, self.quota(five=.7, week=.8))
        self.fire()
        self.assertEqual(
            self.pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now).target_handle,
            self.third,
        )

    def test_equal_quota_keeps_registry_order(self):
        self.pool.record_quota(self.second, ModelGroup.GEMINI, self.quota())
        self.pool.record_quota(self.third, ModelGroup.GEMINI, self.quota())
        self.fire()
        self.assertEqual(
            self.pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now).target_handle,
            self.second,
        )

    def test_missing_credential_skipped(self):
        self.stored.remove(self.second)
        self.pool.record_quota(self.second, ModelGroup.GEMINI, self.quota())
        self.fire()
        self.assertIsNone(self.pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now))

    def test_unknown_or_stale_or_disabled_windows_fail_closed(self):
        for quota in (
            self.quota(five=None),
            self.quota(age=301),
            self.quota(five=0, reset=self.now-10),
            self.quota(disabled=True),
        ):
            with self.subTest(quota=quota):
                self.pool.record_quota(self.second, ModelGroup.GEMINI, quota)
                self.fire()
                self.assertIsNone(self.pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now))

    def test_only_fresh_known_both_windows_eligible(self):
        self.pool.record_quota(
            self.second, ModelGroup.GEMINI,
            GroupQuota(QuotaWindow(.9, self.now), QuotaWindow(None, self.now)),
        )
        self.fire()
        self.assertIsNone(self.pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now))

    def test_expired_reset_does_not_fake_refill(self):
        q = QuotaWindow(0, self.now, reset_at=self.now-100)
        self.assertEqual(q.status(self.now), QuotaStatus.EXHAUSTED)

    def test_401_and_403_never_trigger_rotation(self):
        for status in (401, 403):
            with self.subTest(status=status):
                pool = AccountPool((self.first, self.second), lambda h: True)
                pool.record_quota(self.second, ModelGroup.GEMINI, self.quota())
                pool.record_http_error(self.first, ModelGroup.GEMINI, status, self.now)
                self.assertIsNone(pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now))

    def test_401_after_429_blocks_rotation(self):
        self.pool.record_quota(self.second, ModelGroup.GEMINI, self.quota())
        self.fire()
        self.pool.record_http_error(self.first, ModelGroup.GEMINI, 403, self.now)
        self.assertIsNone(self.pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now))

    def test_429_cooldown_restricts_target(self):
        self.pool.record_quota(self.second, ModelGroup.GEMINI, self.quota())
        self.pool.record_http_error(self.second, ModelGroup.GEMINI, 429, self.now)
        self.fire()
        self.assertIsNone(self.pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now))

    def test_disabled_candidates_skipped(self):
        self.pool.record_quota(self.second, ModelGroup.GEMINI, self.quota())
        self.pool.enable(self.second, False)
        self.fire()
        self.assertIsNone(self.pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now))

    def test_fail_closed_on_vault_exception(self):
        pool = AccountPool((self.first, self.second), lambda h: 1/0)
        pool.record_quota(self.second, ModelGroup.GEMINI, self.quota())
        pool.record_http_error(self.first, ModelGroup.GEMINI, 429, self.now)
        self.assertIsNone(pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now))

    def test_wrong_model_group_never_inherits_quota(self):
        self.pool.record_quota(self.second, ModelGroup.GEMINI, self.quota())
        self.fire(ModelGroup.CLAUDE_GPT)
        self.assertIsNone(
            self.pool.propose_after_429(self.first, ModelGroup.CLAUDE_GPT, self.now)
        )

    def test_validation_and_rejection(self):
        with self.assertRaises(PoolError):
            AccountPool(("email@example.test",), lambda h: True)
        with self.assertRaises(PoolError):
            AccountPool((self.first, self.first), lambda h: True)
        for bad in (-.01, 1.01, float("nan"), float("inf"), True):
            with self.subTest(bad=bad), self.assertRaises(PoolError):
                QuotaWindow(bad, self.now)
        with self.assertRaises(PoolError):
            self.pool.record_http_error(self.first, ModelGroup.GEMINI, True, self.now)

    def test_summary_redacts_ids_and_secrets(self):
        self.pool.record_quota(self.second, ModelGroup.GEMINI, self.quota())
        self.fire()
        plan = self.pool.propose_after_429(self.first, ModelGroup.GEMINI, self.now)
        out = repr(plan) + json.dumps(plan.safe_summary())
        out += json.dumps(self.pool.safe_summary(ModelGroup.GEMINI, self.now))
        for value in (self.first, self.second, "refresh_token", "email@example"):
            self.assertNotIn(value, out)

    def test_demo_never_accesses_live_account(self):
        output = synthetic_demo()
        self.assertEqual(output["mode"], "synthetic_only")
        self.assertTrue(output["handoff"]["candidate_found"])
        self.assertFalse(output["handoff"]["account_switched"])
        self.assertNotIn("raif-", json.dumps(output))


if __name__ == "__main__":
    unittest.main()
