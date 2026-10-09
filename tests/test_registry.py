"""Synthetic tests: no live OAuth data or external Antigravity interaction."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raif_ag_supervisor.registry import LocalAccountRegistry, RegistryError
from raif_ag_supervisor.vault import InMemoryTestVault


def manifest():
    return json.dumps([
        {"email": "alpha@example.test", "refresh_token": "synthetic-alpha"},
        {"email": "beta@example.test", "refresh_token": "synthetic-beta"},
    ]).encode("utf-8")


class FailingVault(InMemoryTestVault):
    writes = 0

    def put(self, account_id, secret):
        self.writes += 1
        super().put(account_id, secret)
        if self.writes == 2:
            raise RuntimeError("synthetic-alpha-secret-must-not-leak")


class InterruptedVault(InMemoryTestVault):
    writes = 0

    def put(self, account_id, secret):
        self.writes += 1
        super().put(account_id, secret)
        if self.writes == 1:
            raise SystemExit("simulated process termination")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="raif-registry-")
        self.addCleanup(self.directory.cleanup)
        self.registry = LocalAccountRegistry(Path(self.directory.name))
        self.vault = InMemoryTestVault()

    def test_empty_registry(self):
        self.assertEqual(self.registry.ids(), ())
        self.assertEqual(self.registry.recover(self.vault), "clean")

    def test_import_persists_only_opaque_ids(self):
        handles = self.registry.import_manifest(manifest(), self.vault)
        self.assertEqual(len(handles), 2)
        self.assertEqual(self.registry.ids(), handles)
        self.assertFalse(self.registry.pending_path.exists())
        self.assertTrue(all(self.vault.has(x) for x in handles))
        self.assertNotIn("synthetic-", self.registry.registry_path.read_text())
        self.assertNotIn("example.test", self.registry.registry_path.read_text())
        self.assertNotIn("secret", repr(self.registry))

    def test_normal_failure_removes_staged_credentials(self):
        vault = FailingVault()
        with self.assertRaises(RegistryError) as failure:
            self.registry.import_manifest(manifest(), vault)
        self.assertEqual(vault._values, {})
        self.assertEqual(self.registry.ids(), ())
        self.assertFalse(self.registry.pending_path.exists())
        self.assertNotIn("synthetic-alpha", str(failure.exception))

    def test_crash_in_vault_put_recovers_to_clean_state(self):
        vault = InterruptedVault()
        with self.assertRaises(SystemExit):
            self.registry.import_manifest(manifest(), vault)
        self.assertTrue(self.registry.pending_path.exists())
        self.assertEqual(self.registry.ids(), ())
        self.assertEqual(self.registry.recover(vault), "rolled_back")
        self.assertEqual(vault._values, {})
        self.assertFalse(self.registry.pending_path.exists())

    def test_crash_after_registry_commit_preserves_credentials(self):
        original_unlink = Path.unlink
        def interrupted_unlink(path, *args, **kwargs):
            if path == self.registry.pending_path:
                raise SystemExit("simulated process termination")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", interrupted_unlink):
            with self.assertRaises(SystemExit):
                self.registry.import_manifest(manifest(), self.vault)
        committed = self.registry.ids()
        self.assertEqual(len(committed), 2)
        self.assertTrue(self.registry.pending_path.exists())
        self.assertEqual(self.registry.recover(self.vault), "committed")
        self.assertTrue(all(self.vault.has(x) for x in committed))
        self.assertFalse(self.registry.pending_path.exists())

    def test_pending_journal_blocks_new_import(self):
        with patch.object(Path, "unlink", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.registry.import_manifest(manifest(), self.vault)
        with self.assertRaises(RegistryError):
            self.registry.import_manifest(manifest(), self.vault)
        self.assertEqual(self.registry.recover(self.vault), "committed")

    def test_malformed_registry_never_loaded(self):
        self.registry.registry_path.write_text('{"version":1,"accounts":[],"refresh_token":"synthetic"}')
        with self.assertRaises(RegistryError):
            self.registry.ids()

    def test_generated_collision_does_not_overwrite(self):
        account_id = "raif-" + "a" * 32
        self.vault.put(account_id, "synthetic-preserved")
        with patch("raif_ag_supervisor.registry.secrets.token_hex", return_value="a" * 32):
            with self.assertRaises(RegistryError):
                self.registry.import_manifest(manifest(), self.vault)
        self.assertEqual(self.vault._values[account_id], "synthetic-preserved")
        self.assertFalse(self.registry.pending_path.exists())


if __name__ == "__main__":
    unittest.main()
