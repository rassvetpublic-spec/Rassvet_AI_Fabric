import unittest
from raif_ag_supervisor.vault import InMemoryTestVault

class VaultTests(unittest.TestCase):
    def test_store_and_delete_synthetic(self):
        vault = InMemoryTestVault()
        vault.put("local-1", "synthetic-credential")
        self.assertTrue(vault.has("local-1"))
        self.assertNotIn("synthetic-credential", repr(vault))
        vault.delete("local-1")
        self.assertFalse(vault.has("local-1"))

    def test_reject_non_synthetic_credentials(self):
        vault = InMemoryTestVault()
        with self.assertRaises(ValueError):
            vault.put("local-1", "unrecognized-secret")
        self.assertFalse(vault.has("local-1"))

    def test_reject_empty_credentials(self):
        with self.assertRaises(ValueError):
            InMemoryTestVault().put("local-1", "")

if __name__ == "__main__":
    unittest.main()
