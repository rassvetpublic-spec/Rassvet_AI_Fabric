import json
import os
import unittest
from unittest.mock import patch

from raif_ag_supervisor.vault import InMemoryTestVault
from raif_ag_supervisor.transaction import (
    ImportTransactionError, import_into_vault,
)
from raif_ag_supervisor.importer import ImportFormatError
from raif_ag_supervisor.windows_vault import WindowsCredentialVault


def synthetic_manifest():
    return json.dumps([
        {"email": "alpha@example.test", "refresh_token": "synthetic-alpha"},
        {"email": "beta@example.test", "refresh_token": "synthetic-beta"},
    ]).encode("utf-8")


class FailOnSecondWrite(InMemoryTestVault):
    attempts = 0

    def put(self, account_id, secret):
        self.attempts += 1
        super().put(account_id, secret)
        if self.attempts == 2:
            raise RuntimeError("internal synthetic-alpha failure must not be exposed")


class ImportTransactionTests(unittest.TestCase):
    def test_success_only_returns_opaque_handles(self):
        vault = InMemoryTestVault()
        accounts = import_into_vault(synthetic_manifest(), vault)
        self.assertEqual(len(accounts), 2)
        self.assertNotEqual(accounts[0].account_id, accounts[1].account_id)
        self.assertTrue(all(vault.has(a.account_id) for a in accounts))
        self.assertNotIn("synthetic-", repr(accounts))
        self.assertNotIn("alpha@example.test", repr(accounts))

    def test_failed_import_rolls_back_all_new_entries(self):
        vault = FailOnSecondWrite()
        with self.assertRaises(ImportTransactionError) as ctx:
            import_into_vault(synthetic_manifest(), vault)
        self.assertEqual(vault._values, {})
        self.assertNotIn("synthetic-", str(ctx.exception))

    def test_duplicate_rejected_before_first_write(self):
        data = json.dumps([
            {"email": "alpha@example.test", "refresh_token": "synthetic-a"},
            {"email": "ALPHA@example.test", "refresh_token": "synthetic-b"},
        ]).encode("utf-8")
        vault = InMemoryTestVault()
        with self.assertRaises(ImportFormatError):
            import_into_vault(data, vault)
        self.assertEqual(vault._values, {})

    @unittest.skipUnless(os.name == "nt", "Windows-only native integration")
    def test_native_import_uses_raif_namespace_only(self):
        vault = WindowsCredentialVault()
        imported = import_into_vault(synthetic_manifest(), vault)
        try:
            self.assertEqual(len(imported), 2)
            self.assertTrue(all(vault.has(x.account_id) for x in imported))
        finally:
            for handle in imported:
                vault.delete(handle.account_id)
        self.assertTrue(all(not vault.has(x.account_id) for x in imported))

    def test_colliding_generated_id_is_not_overwritten(self):
        vault = InMemoryTestVault()
        with patch("raif_ag_supervisor.transaction.secrets.token_hex", return_value="1" * 32):
            with self.assertRaises(ImportTransactionError):
                import_into_vault(synthetic_manifest(), vault)
        self.assertEqual(vault._values, {})


if __name__ == "__main__":
    unittest.main()
