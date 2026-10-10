"""Offline-only tests; no user tokens, LS connection or provider requests."""
import json
import unittest
from raif_ag_supervisor.native_rpc import LocalRpcTarget
from raif_ag_supervisor.quota_observer import (
    summarize_native_quota_response, collect_native_quota,
)

TIMESTAMP = 1700000000.0

def group(name, a=.7, b=.8, *, include_disabled=True):
    first = {"window":"5h","remainingFraction":a}
    second = {"window":"weekly","remainingFraction":b}
    if include_disabled:
        first["disabled"] = False
        second["disabled"] = False
    return {"displayName":name, "buckets":[first,second]}

class NativeQuotaReportTests(unittest.TestCase):
    def test_known_groups_and_fractions(self):
        p = {"response":{"groups":[group("Gemini Models"), group("Claude and GPT models",1.,1.)],
             "email":"secret@example.test","refreshToken":"NEVER_EXPORT"}}
        r = summarize_native_quota_response(p, observed_at=TIMESTAMP)
        self.assertEqual(r["verdict"], "QUOTA_OBSERVED")
        self.assertEqual({x["group"] for x in r["groups"]},{"gemini","claude_gpt"})
        self.assertAlmostEqual(r["groups"][0]["five_hour"]["remaining_fraction"],.7)
        self.assertEqual(r["groups"][0]["weekly"]["status"],"ready")
        self.assertFalse(r["account_identity_verified"])
        self.assertFalse(r["eligible_for_pool"])
        text = json.dumps(r)
        for sensitive in ("secret@example.test","NEVER_EXPORT","refreshToken"):
            self.assertNotIn(sensitive,text)

    def test_missing_disabled_never_ready(self):
        p = {"groups":[group("Gemini Models",.6866705,.6757333,include_disabled=False)]}
        r = summarize_native_quota_response(p, observed_at=TIMESTAMP)
        g = r["groups"][0]
        self.assertEqual(g["five_hour"]["status"],"unknown")
        self.assertEqual(g["weekly"]["status"],"unknown")
        self.assertIsNone(g["five_hour"]["disabled"])
        self.assertFalse(r["eligible_for_pool"])

    def test_unknown_groups_not_guessed(self):
        r = summarize_native_quota_response({"groups":[group("Unrelated Model")]},
                                             observed_at=TIMESTAMP)
        self.assertEqual(r["verdict"],"NO_RECOGNIZED_QUOTA_GROUPS")
        self.assertEqual(r["groups"],[])

    def test_denied_optin_does_not_call_sender(self):
        called=[]
        def sender(*a,**k):
            called.append(True)
            raise AssertionError("network called")
        r=collect_native_quota(LocalRpcTarget(1234,"csrf"),allow_quota_read=False,
          ownership_verified=lambda:True,observed_at=TIMESTAMP,sender=sender)
        self.assertEqual(r["verdict"],"RPC_QUOTA_OPT_IN_REQUIRED")
        self.assertEqual(called,[])

    def test_failed_owner_does_not_call_sender(self):
        calls=[]
        def sender(*a,**k):
            calls.append(True)
            return {"groups":[]}
        r=collect_native_quota(LocalRpcTarget(1234,"csrf"),allow_quota_read=True,
          ownership_verified=lambda:False,observed_at=TIMESTAMP,sender=sender)
        self.assertEqual(r["verdict"],"RPC_OWNER_EVIDENCE_FAILED")
        self.assertEqual(calls,[])

    def test_owner_verified_collects_only_safe_values(self):
        observed=[]
        def sender(target,**opts):
            observed.append(opts["allow_quota_read"])
            return {"groups":[group("Gemini Models")],"projectId":"private-project"}
        r=collect_native_quota(LocalRpcTarget(1234,"csrf"),allow_quota_read=True,
          ownership_verified=lambda:True,observed_at=TIMESTAMP,sender=sender)
        self.assertEqual(observed,[True])
        self.assertEqual(r["verdict"],"QUOTA_OBSERVED")
        self.assertNotIn("private-project",json.dumps(r))

    def test_sender_error_redacted(self):
        def sender(*_a,**_kw): raise RuntimeError("private-oauth-value")
        r=collect_native_quota(LocalRpcTarget(1234,"csrf"),allow_quota_read=True,
          ownership_verified=lambda:True,observed_at=TIMESTAMP,sender=sender)
        self.assertEqual(r["verdict"],"QUOTA_OBSERVATION_FAILED")
        self.assertNotIn("private-oauth-value",json.dumps(r))

    def test_invalid_time_blocks_request(self):
        called=[]
        r=collect_native_quota(LocalRpcTarget(1234,"csrf"),allow_quota_read=True,
          ownership_verified=lambda:True,observed_at=float("nan"),
          sender=lambda *a,**k:called.append(1))
        self.assertEqual(r["verdict"],"OBSERVATION_TIME_INVALID")
        self.assertEqual(called,[])

if __name__=="__main__":
    unittest.main()
