# -*- coding: utf-8 -*-
"""
tests.test_session_adapter - Модульные тесты для session_adapter и token_refresh.
Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / MTD 011011.
"""
import os
import time
import json
import uuid
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from raif_ag_supervisor.token_refresh import (
    mask_email,
    format_antigravity_credential_payload,
    load_cached_profiles,
    TokenRefreshError,
)
from raif_ag_supervisor.session_adapter import (
    StandaloneSessionAdapter,
    SessionAdapterError,
)


class TestTokenRefresh(unittest.TestCase):
    def test_mask_email(self):
        self.assertEqual(mask_email("user@gmail.com"), "u**r@gmail.com")
        self.assertEqual(mask_email("ab@gmail.com"), "a*@gmail.com")
        self.assertEqual(mask_email("alexander@google.com"), "a*******r@google.com")
        self.assertEqual(mask_email("invalid"), "redacted")

    def test_format_payload_schema(self):
        ts = 1791921383.0
        payload = format_antigravity_credential_payload(
            access_token="ya29.synthetic_access",
            refresh_token="1//0synthetic_refresh",
            expiry_timestamp=ts,
            id_token="eyJhbGciOi...",
            auth_method="consumer",
        )
        self.assertEqual(payload["auth_method"], "consumer")
        self.assertEqual(payload["id_token"], "eyJhbGciOi...")
        token_sub = payload["token"]
        self.assertEqual(token_sub["access_token"], "ya29.synthetic_access")
        self.assertEqual(token_sub["refresh_token"], "1//0synthetic_refresh")
        self.assertEqual(token_sub["token_type"], "Bearer")
        self.assertTrue(token_sub["expiry"].endswith("Z"))

    def test_format_payload_missing_token_raises(self):
        with self.assertRaises(TokenRefreshError):
            format_antigravity_credential_payload(
                access_token="",
                refresh_token="valid_refresh",
                expiry_timestamp=time.time(),
            )

    def test_load_cached_profiles_synthetic(self):
        with TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            profile1 = {
                "id": "profile-01",
                "email": "test1@gmail.com",
                "token": {
                    "access_token": "acc1",
                    "refresh_token": "ref1",
                    "expiry_timestamp": time.time() + 3600,
                    "id_token": "id1",
                },
            }
            (tmppath / "p1.json").write_text(json.dumps(profile1), encoding="utf-8")

            # Expired profile
            profile2 = {
                "id": "profile-02",
                "email": "test2@gmail.com",
                "token": {
                    "access_token": "acc2",
                    "refresh_token": "ref2",
                    "expiry_timestamp": time.time() - 100,
                },
            }
            (tmppath / "p2.json").write_text(json.dumps(profile2), encoding="utf-8")

            loaded = load_cached_profiles(accounts_dir=tmppath)
            self.assertEqual(len(loaded), 2)
            self.assertTrue(loaded[0].has_fresh_access)
            self.assertFalse(loaded[1].has_fresh_access)


class TestSessionAdapter(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows-only test")
    def test_synthetic_target_write_read_delete(self):
        # Используем строго изолированный синтетический target
        target = f"RAiF_AG_Supervisor:canary:{uuid.uuid4().hex}"
        adapter = StandaloneSessionAdapter(target_name=target)
        synthetic_payload = {
            "token": {
                "access_token": "synthetic_access",
                "refresh_token": "synthetic_refresh",
                "expiry": "2026-10-13T23:59:59Z",
                "token_type": "Bearer",
            },
            "auth_method": "consumer",
            "id_token": "canary_id",
        }
        try:
            self.assertIsNone(adapter.read_native_credential_bytes())
            self.assertTrue(adapter.write_native_credential_json(synthetic_payload))

            readback = adapter.read_native_credential_json()
            self.assertIsNotNone(readback)
            self.assertEqual(readback["auth_method"], "consumer")
            self.assertEqual(readback["id_token"], "canary_id")
            self.assertEqual(readback["token"]["access_token"], "synthetic_access")
        finally:
            # Очистка синтетического таргета
            adapter._advapi32.CredDeleteW(target, 1, 0)

    @unittest.skipUnless(os.name == "nt", "Windows-only test")
    def test_find_process_returns_identity_or_none(self):
        adapter = StandaloneSessionAdapter()
        proc = adapter.find_language_server_process()
        if proc:
            self.assertEqual(proc.image_name.casefold(), "language_server.exe")
            self.assertGreater(proc.pid, 0)


if __name__ == "__main__":
    unittest.main()
