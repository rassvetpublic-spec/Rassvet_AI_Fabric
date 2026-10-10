"""Synthetic-only tests; never contact Google or a real Language Server."""
import json
import ssl
import unittest
from unittest.mock import patch

from raif_ag_supervisor.native_rpc import (
    LocalRpcTarget, NativeRpcError, NativeRpcObserver,
    _decode_reply, invoke_native_rpc, invoke_native_quota_rpc,
)


class TargetTests(unittest.TestCase):
    def test_accepts_loopback(self):
        self.assertEqual(LocalRpcTarget(12345, "opaque-token").host, "127.0.0.1")

    def test_rejects_remote_address(self):
        for host in ("localhost", "0.0.0.0", "192.168.1.1", "example.com", "::1"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                LocalRpcTarget(12345, "opaque-token", host=host)

    def test_rejects_invalid_ports(self):
        for port in (0, -1, 65536, True, "12345"):
            with self.subTest(port=port), self.assertRaises(ValueError):
                LocalRpcTarget(port, "opaque-token")

    def test_rejects_unsafe_csrf(self):
        for token in ("", "x\r\nsecret: y", "x\ny", "x\t", "é", "x" * 1025):
            with self.subTest(token=token[:10]), self.assertRaises(ValueError):
                LocalRpcTarget(12345, token)

    def test_target_representation_hides_csrf(self):
        self.assertNotIn("not-for-logs", repr(LocalRpcTarget(12345, "not-for-logs")))


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.target = LocalRpcTarget(12345, "safe-placeholder")

    def test_disallows_mutating_methods_before_connection(self):
        for method in ("AuthLogout", "Login", "GetOAuthToken", "GetAvailableModels",
                       "RetrieveUserQuotaSummary", "SwitchAccount", "GetUserStatus"):
            with self.subTest(method=method), self.assertRaises(NativeRpcError) as cm:
                invoke_native_rpc(self.target, method)
            self.assertEqual(cm.exception.code, "RPC_METHOD_NOT_READONLY_ALLOWLISTED")

    def test_timeout_bounds(self):
        for timeout in (0, -2, 20):
            with self.assertRaises(ValueError):
                invoke_native_rpc(self.target, "HasAuthToken", timeout=timeout)

    def test_decode_bounds_and_schema(self):
        for data in (b"not json", b"[]", b"\xff", b"{" + b"x" * 16384):
            with self.subTest(length=len(data)), self.assertRaises(NativeRpcError):
                _decode_reply(data)

    def test_https_transport_is_fixed_local_post_and_no_redirect(self):
        class Response:
            status = 200
            def getheader(self, _): return None
            def read(self, _: int): return b'{"hasToken":true}'
        class Connection:
            used = None
            def __init__(self, host, port, timeout, context):
                self.address = (host, port, timeout)
                self.context = context
                Connection.used = self
            def request(self, verb, path, body, headers):
                self.requested = (verb, path, body, headers)
            def getresponse(self): return Response()
            def close(self): self.closed = True
        with patch("raif_ag_supervisor.native_rpc.http.client.HTTPSConnection", Connection):
            result = invoke_native_rpc(self.target, "HasAuthToken")
        self.assertEqual(result, {"hasToken": True})
        self.assertEqual(Connection.used.address[:2], ("127.0.0.1", 12345))
        self.assertFalse(Connection.used.context.check_hostname)
        self.assertEqual(Connection.used.context.verify_mode, ssl.CERT_NONE)
        verb, path, body, headers = Connection.used.requested
        self.assertEqual((verb, path, body), ("POST", "/exa.language_server_pb.LanguageServerService/HasAuthToken", b"{}"))
        self.assertEqual(headers["connect-protocol-version"], "1")
        self.assertEqual(headers["x-codeium-csrf-token"], "safe-placeholder")
        self.assertTrue(Connection.used.closed)

    def test_http_error_does_not_echo_body_or_csrf(self):
        class Connection:
            def __init__(self, *_a, **_kw): pass
            def request(self, *_a, **_kw): pass
            def getresponse(self):
                class Response:
                    status = 302
                return Response()
            def close(self): pass
        with patch("raif_ag_supervisor.native_rpc.http.client.HTTPSConnection", Connection):
            with self.assertRaises(NativeRpcError) as cm:
                invoke_native_rpc(self.target, "GetAuthStatus")
        self.assertEqual(str(cm.exception), "RPC_HTTP_NON_200")

    def test_transport_exception_redacts_private_error(self):
        class Connection:
            def __init__(self, *_a, **_kw): pass
            def request(self, *_a, **_kw):
                raise OSError("private-access-token-in-exception")
            def close(self): pass
        with patch("raif_ag_supervisor.native_rpc.http.client.HTTPSConnection", Connection):
            with self.assertRaises(NativeRpcError) as cm:
                invoke_native_rpc(self.target, "HasAuthToken")
        self.assertEqual(str(cm.exception), "RPC_TRANSPORT_FAILED")
        self.assertNotIn("private-access-token", repr(cm.exception))

    def test_invalid_remote_target_not_accepted_before_tls(self):
        with self.assertRaises(ValueError):
            LocalRpcTarget(12345, "csrf", host="remote.example")

    def test_oversize_http_body_is_refused(self):
        class Connection:
            def __init__(self, *_a, **_kw): pass
            def request(self, *_a, **_kw): pass
            def getresponse(self):
                class Response:
                    status = 200
                    def getheader(self, _): return None
                    def read(self, _): return b"x" * 20000
                return Response()
            def close(self): pass
        with patch("raif_ag_supervisor.native_rpc.http.client.HTTPSConnection", Connection):
            with self.assertRaises(NativeRpcError) as cm:
                invoke_native_rpc(self.target, "GetAuthStatus")
        self.assertEqual(cm.exception.code, "RPC_RESPONSE_SIZE_INVALID")


class ObserverTests(unittest.TestCase):
    def test_only_safe_flags_escape(self):
        secret = "super-secret-access-token"
        def send(_target, method):
            if method == "HasAuthToken":
                return {"hasToken": True, "email": "personal@example.com", "token": secret}
            return {"authResult": {"hasValidAuth": True, "privateToken": secret}}
        report = NativeRpcObserver(LocalRpcTarget(1234, "private-csrf"), send).observe()
        self.assertEqual(report["has_token_reported"], True)
        self.assertEqual(report["local_auth_flag_untrusted"], True)
        self.assertFalse(report["account_identity_verified"])
        self.assertFalse(report["session_switch_verified"])
        encoded = json.dumps(report)
        self.assertNotIn(secret, encoded)
        self.assertNotIn("personal@example.com", encoded)
        self.assertNotIn("private-csrf", encoded)

    def test_auth_flag_not_identity(self):
        report = NativeRpcObserver(LocalRpcTarget(1234, "csrf"),
            lambda t, method: ({"hasToken": False} if method == "HasAuthToken" else {"authResult": {"hasValidAuth": True}})).observe()
        self.assertTrue(report["local_auth_flag_untrusted"])
        self.assertFalse(report["provider_access_verified"])

    def test_schema_errors_are_redacted(self):
        def send(_target, method):
            return {"hasToken": 1} if method == "HasAuthToken" else {"authResult": []}
        report = NativeRpcObserver(LocalRpcTarget(1234, "csrf"), send).observe()
        self.assertEqual(set(report["method_status"].values()), {"RPC_FLAG_SCHEMA_INVALID", "RPC_RESPONSE_SCHEMA_INVALID"})

    def test_missing_bool_is_unknown(self):
        report = NativeRpcObserver(LocalRpcTarget(1234, "csrf"), lambda _t,_m: {}).observe()
        self.assertIsNone(report["has_token_reported"])
        self.assertIsNone(report["local_auth_flag_untrusted"])

    def test_exception_payload_is_never_logged(self):
        def boom(_target, _method):
            raise RuntimeError("private-client-secret")
        report = NativeRpcObserver(LocalRpcTarget(1234, "csrf"), boom).observe()
        self.assertNotIn("private-client-secret", str(report))
        self.assertEqual(set(report["method_status"].values()), {"RPC_OBSERVATION_FAILED"})


class NativeQuotaWireTests(unittest.TestCase):
    def setUp(self):
        self.target = LocalRpcTarget(19876, "opaque-test-csrf")

    def test_unauthorized_network_does_not_start(self):
        with patch("raif_ag_supervisor.native_rpc.http.client.HTTPSConnection") as conn:
            for args in (
                {},
                {"allow_quota_read": True},
                {"allow_quota_read": 1, "ownership_verified": lambda: True},
                {"allow_quota_read": True, "ownership_verified": lambda: False},
            ):
                with self.subTest(args=tuple(args)), self.assertRaises(NativeRpcError):
                    invoke_native_quota_rpc(self.target, **args)
            conn.assert_not_called()

    def test_quota_request_fixed_https_localhost_and_small_body(self):
        class Response:
            status = 200
            def getheader(self, _): return None
            def read(self, _): return b'{"response":{"groups":[]}}'
        class Connection:
            used = None
            def __init__(self, host, port, timeout, context):
                self.location = (host, port)
                self.tls = context
                Connection.used = self
            def request(self, verb, path, body, headers):
                self.requested = (verb, path, body, headers)
            def getresponse(self): return Response()
            def close(self): self.closed = True
        with patch("raif_ag_supervisor.native_rpc.http.client.HTTPSConnection", Connection):
            received = invoke_native_quota_rpc(
                self.target, allow_quota_read=True, ownership_verified=lambda: True,
            )
        self.assertEqual(received, {"response": {"groups": []}})
        c = Connection.used
        self.assertEqual(c.location, ("127.0.0.1", 19876))
        self.assertEqual(
            c.requested[:3],
            ("POST",
             "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
             b'{"request":{},"forceRefresh":false}'),
        )
        self.assertEqual(c.requested[3]["x-codeium-csrf-token"], "opaque-test-csrf")
        self.assertTrue(c.closed)

    def test_oversize_quota_response_rejected(self):
        class Response:
            status = 200
            def getheader(self, _): return None
            def read(self, _): return b"x" * (256 * 1024 + 1)
        class Connection:
            def __init__(self, *_a, **_kw): pass
            def request(self, *_a, **_kw): pass
            def getresponse(self): return Response()
            def close(self): pass
        with patch("raif_ag_supervisor.native_rpc.http.client.HTTPSConnection", Connection):
            with self.assertRaises(NativeRpcError) as cm:
                invoke_native_quota_rpc(
                    self.target, allow_quota_read=True, ownership_verified=lambda: True,
                )
        self.assertEqual(cm.exception.code, "RPC_RESPONSE_SIZE_INVALID")

    def test_owner_exception_is_never_exposed(self):
        def verifier():
            raise RuntimeError("secret-personal-host-path")
        with self.assertRaises(NativeRpcError) as cm:
            invoke_native_quota_rpc(self.target, allow_quota_read=True, ownership_verified=verifier)
        self.assertEqual(str(cm.exception), "RPC_OWNER_EVIDENCE_FAILED")


if __name__ == "__main__":
    unittest.main()
