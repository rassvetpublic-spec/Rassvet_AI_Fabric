"""Synthetic-only Windows Credential Manager integration tests.

No OAuth tokens, user's exported files, or application credentials involved.
"""
import os
import unittest
import uuid

from raif_ag_supervisor.windows_vault import (
    WindowsCredentialVault, CredentialVaultError, _target,
)


class PlatformIndependentValidation(unittest.TestCase):
    def test_scoped_target(self):
        self.assertEqual(
            _target("synthetic.01"),
            "RAiF_AG_Supervisor:account:synthetic.01",
        )

    def test_invalid_ids_never_touch_credentials(self):
        for identifier in ("", "../gemini:antigravity", "name:other", " ", "a" * 65):
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):
                    _target(identifier)

    @unittest.skipUnless(os.name == "nt", "Windows-only native interface")
    def test_native_roundtrip_with_synthetic_value(self):
        vault = WindowsCredentialVault()
        account = "ci-" + uuid.uuid4().hex
        value = "synthetic-" + uuid.uuid4().hex
        try:
            self.assertFalse(vault.has(account))
            vault.put(account, value)
            self.assertTrue(vault.has(account))
            self.assertNotIn(value, repr(vault))
        finally:
            vault.delete(account)
        self.assertFalse(vault.has(account))

    @unittest.skipUnless(os.name == "nt", "Windows-only native interface")
    def test_native_write_limits_and_invalid_data(self):
        vault = WindowsCredentialVault()
        account = "ci-" + uuid.uuid4().hex
        with self.assertRaises(ValueError):
            vault.put(account, "")
        with self.assertRaises(ValueError):
            vault.put(account, "synthetic-" + "x" * 3000)
        self.assertFalse(vault.has(account))


if __name__ == "__main__":
    unittest.main()
