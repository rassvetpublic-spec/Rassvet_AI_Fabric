import json
import unittest

from raif_ag_supervisor.pool import ModelGroup, QuotaStatus
from raif_ag_supervisor.quota_adapter import QuotaParseError, parse_quota_summary


OBS = 1_700_000_000.0


def group(name="Gemini Models", five=.7, week=.4, **overrides):
    buckets = [
        {"window": "5h", "remainingFraction": five, "disabled": False},
        {"window": "weekly", "remainingFraction": week, "disabled": False},
    ]
    buckets[0].update(overrides)
    return {"displayName": name, "buckets": buckets}


class QuotaAdapterTests(unittest.TestCase):
    def parse(self, groups):
        return parse_quota_summary({"response": {"groups": groups}}, observed_at=OBS)

    def test_recognized_model_groups(self):
        result = self.parse([group(), group("Claude and GPT models", .9, .8)])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[ModelGroup.GEMINI].score(OBS), .4)
        self.assertEqual(result[ModelGroup.CLAUDE_GPT].score(OBS), .8)

    def test_case_insensitive_group_name(self):
        result = self.parse([group("  GEMINI  MODELS ")])
        self.assertIn(ModelGroup.GEMINI, result)

    def test_unknown_groups_not_guessed(self):
        result = self.parse([group("Other Vendor Models")])
        self.assertEqual(result, {})

    def test_missing_weekly_window_skipped(self):
        sample = group()
        sample["buckets"].pop()
        self.assertEqual(self.parse([sample]), {})

    def test_unknown_fraction_not_considered_ready(self):
        result = self.parse([group(five="unavailable")])
        self.assertIsNone(result[ModelGroup.GEMINI].score(OBS))
        self.assertEqual(result[ModelGroup.GEMINI].five_hour.status(OBS), QuotaStatus.UNKNOWN)

    def test_boolean_and_negative_remaining_rejected(self):
        for value in (True, -0.1, 1.1):
            with self.subTest(value=value):
                result = self.parse([group(five=value)])
                self.assertIsNone(result[ModelGroup.GEMINI].score(OBS))

    def test_missing_disabled_is_unknown_even_when_fraction_positive(self):
        payload = group()
        for bucket in payload["buckets"]:
            bucket.pop("disabled")
        result = self.parse([payload])
        gemini = result[ModelGroup.GEMINI]
        self.assertEqual(gemini.five_hour.status(OBS), QuotaStatus.UNKNOWN)
        self.assertEqual(gemini.weekly.status(OBS), QuotaStatus.UNKNOWN)
        self.assertIsNone(gemini.score(OBS))

    def test_one_window_missing_disabled_prevents_selection(self):
        payload = group()
        payload["buckets"][1].pop("disabled")
        self.assertIsNone(self.parse([payload])[ModelGroup.GEMINI].score(OBS))

    def test_explicit_disabled_false_preserves_known_available_snapshot(self):
        self.assertEqual(self.parse([group()])[ModelGroup.GEMINI].score(OBS), .4)

    def test_disabled_removes_candidate(self):
        result = self.parse([group(disabled=True)])
        self.assertIsNone(result[ModelGroup.GEMINI].score(OBS))

    def test_malformed_disabled_is_fail_closed(self):
        result = self.parse([group(disabled="false")])
        self.assertIsNone(result[ModelGroup.GEMINI].score(OBS))

    def test_reset_in_past_does_not_infer_refill(self):
        result = self.parse([group(five=0, resetTime="2020-01-01T00:00:00Z")])
        self.assertEqual(result[ModelGroup.GEMINI].five_hour.status(OBS), QuotaStatus.EXHAUSTED)
        self.assertIsNone(result[ModelGroup.GEMINI].score(OBS))

    def test_duplicate_quota_group_rejected(self):
        with self.assertRaises(QuotaParseError):
            self.parse([group(), group("gemini models")])

    def test_duplicate_window_rejected(self):
        payload = group()
        payload["buckets"].append({"window": "5h", "remainingFraction": 1})
        with self.assertRaises(QuotaParseError):
            self.parse([payload])

    def test_unknown_or_large_payload_rejected(self):
        for payload in (b"garbage", b" " * (1024 * 1024 + 1), b"[]", []):
            with self.subTest(type=type(payload)), self.assertRaises(QuotaParseError):
                parse_quota_summary(payload, observed_at=OBS)

    def test_parse_json_bytes(self):
        body = json.dumps({"groups": [group()]}).encode("utf-8")
        self.assertIn(ModelGroup.GEMINI, parse_quota_summary(body, observed_at=OBS))

    def test_invalid_observed_at_rejected(self):
        with self.assertRaises(QuotaParseError):
            parse_quota_summary({"groups": []}, observed_at=float("nan"))

    def test_no_raw_secret_in_exception(self):
        payload = {"groups": [group(), group()], "token": "synthetic-do-not-print"}
        try:
            parse_quota_summary(payload, observed_at=OBS)
        except QuotaParseError as exc:
            self.assertNotIn("synthetic-do-not-print", str(exc))
        else:
            self.fail("expected a quota parse error")


if __name__ == "__main__":
    unittest.main()
