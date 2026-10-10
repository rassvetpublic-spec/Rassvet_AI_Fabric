"""CP-54B3 synthetic-only tests; no live LS, credential or provider calls."""
import json
import unittest
from unittest.mock import patch

from raif_ag_supervisor.native_rpc import LocalRpcTarget, NativeRpcError
from raif_ag_supervisor.identity_observer import (
    _MAX_STATUS_BYTES, collect_active_identity, summarize_active_identity,
)


class IdentitySchemaTests(unittest.TestCase):
    def test_status_presence_is_not_identity_binding(self):
        payload = {"response": {"userStatus": {"email": "private@example.test",
                 "refreshToken": "SECRET_VALUE"}, "planInfo": {"name": "private-plan"}}}
        report = summarize_active_identity(payload)
        self.assertEqual(report["verdict"], "IDENTITY_UNVERIFIED")
        self.assertTrue(report["user_status_present"])
        self.assertTrue(report["plan_info_present"])
        self.assertFalse(report["account_identity_verified"])
        self.assertFalse(report["eligible_for_pool"])
        self.assertIsNone(report["matched_account_id"])
        safe = json.dumps(report, ensure_ascii=False)
        for secret in ("private@example.test", "SECRET_VALUE", "private-plan"):
            self.assertNotIn(secret, safe)

    def test_snake_case_schema_is_not_provider_proof(self):
        report = summarize_active_identity({"user_status": {}, "plan_info": {}})
        self.assertEqual(report["verdict"], "IDENTITY_UNVERIFIED")
        self.assertFalse(report["provider_access_verified"])

    def test_missing_user_status_cannot_be_guessed_from_plan_or_token(self):
        report = summarize_active_identity({"planInfo": {}, "hasValidAuth": True,
                                            "email": "should-never-count@example.test"})
        self.assertEqual(report["verdict"], "USER_STATUS_NOT_PRESENT")
        self.assertFalse(report["user_status_present"])

    def test_untrusted_schema_and_conflicting_aliases_fail_closed(self):
        for payload in ([], None, {"response": []}, {"userStatus": "private"},
                        {"planInfo": "private"},
                        {"userStatus": {}, "user_status": {}},
                        {"planInfo": {}, "plan_info": {}}):
            with self.subTest(kind=str(type(payload))):
                report = summarize_active_identity(payload)
                self.assertIn(report["verdict"],
                    ("IDENTITY_SCHEMA_UNSUPPORTED", "IDENTITY_SCHEMA_AMBIGUOUS"))
                self.assertFalse(report["account_identity_verified"])
                self.assertIsNone(report["matched_account_id"])

    def test_large_private_user_status_has_bounded_output(self):
        report = summarize_active_identity({"userStatus": {"private": "X" * 500000}})
        self.assertLess(len(json.dumps(report)), 550)


class IdentityCollectionTests(unittest.TestCase):
    def setUp(self):
        self.target = LocalRpcTarget(12345, "do-not-export-csrf")

    def test_no_opt_in_never_contacts_sender(self):
        with patch("raif_ag_supervisor.identity_observer._post_fixed_local_rpc") as rpc:
            report = collect_active_identity(self.target, ownership_verified=lambda: True)
        rpc.assert_not_called()
        self.assertEqual(report["verdict"], "IDENTITY_OPT_IN_REQUIRED")

    def test_owner_missing_false_and_error_never_contact_sender(self):
        called = []
        def sender(_target):
            called.append(1)
            return {"userStatus": {}}
        for owner in (None, lambda: False, lambda: 1,
                      lambda: (_ for _ in ()).throw(RuntimeError("SECRET_OWNER"))):
            with self.subTest(owner=owner is None):
                report = collect_active_identity(self.target, allow_identity_read=True,
                    ownership_verified=owner, sender=sender)
                self.assertIn(report["verdict"],
                              ("RPC_OWNER_EVIDENCE_REQUIRED", "RPC_OWNER_EVIDENCE_FAILED"))
        self.assertEqual(called, [])

    def test_only_fixed_method_and_limited_transport(self):
        with patch("raif_ag_supervisor.identity_observer._post_fixed_local_rpc",
                   return_value={"userStatus": {}}) as rpc:
            report = collect_active_identity(self.target, allow_identity_read=True,
                                             ownership_verified=lambda: True)
        rpc.assert_called_once_with(self.target, "GetUserStatus", b"{}",
                                    timeout=2.0, max_bytes=256 * 1024)
        self.assertEqual(_MAX_STATUS_BYTES, 256 * 1024)
        self.assertEqual(report["verdict"], "IDENTITY_UNVERIFIED")

    def test_fixed_errors_only_and_no_private_exception_text(self):
        for error, expected in ((NativeRpcError("RPC_RESPONSE_SIZE_INVALID"),
                                  "RPC_RESPONSE_SIZE_INVALID"),
                                (NativeRpcError("refresh-secret@example.test"),
                                  "IDENTITY_OBSERVATION_FAILED"),
                                (RuntimeError("private-access-token"),
                                  "IDENTITY_OBSERVATION_FAILED")):
            def fail(_target, exception=error):
                raise exception
            with self.subTest(expected=expected):
                result = collect_active_identity(self.target, allow_identity_read=True,
                    ownership_verified=lambda: True, sender=fail)
                self.assertEqual(result["verdict"], expected)
                text = json.dumps(result)
                self.assertNotIn("private", text)
                self.assertNotIn("refresh-secret", text)
                self.assertNotIn("do-not-export-csrf", text)

    def test_bad_target_not_used(self):
        report = collect_active_identity("remote-target", allow_identity_read=True,
                                         ownership_verified=lambda: True)
        self.assertEqual(report["verdict"], "IDENTITY_TARGET_INVALID")

    def test_live_transport_rejects_oversize_body_without_echo(self):
        class Response:
            status = 200
            def getheader(self, _): return None
            def read(self, count): return b"Z" * count
        class Connection:
            def __init__(self, *_args, **_kwargs): pass
            def request(self, *_args, **_kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        with patch("raif_ag_supervisor.native_rpc.http.client.HTTPSConnection", Connection):
            result = collect_active_identity(self.target, allow_identity_read=True,
                                             ownership_verified=lambda: True)
        self.assertEqual(result["verdict"], "RPC_RESPONSE_SIZE_INVALID")
        self.assertFalse(result["account_identity_verified"])


if __name__ == "__main__":
    unittest.main()
