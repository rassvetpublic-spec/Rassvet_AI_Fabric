import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raif_ag_supervisor.accounts_cli import main
from raif_ag_supervisor.vault import InMemoryTestVault


def rows():
    return [
        {"email": "synthetic@example.test", "refresh_token": "synthetic-token"},
        {"email": "test@example.test", "refresh_token": "synthetic-credential"},
    ]


class LocalAccountsCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="raif-accounts-cli-")
        self.addCleanup(self.temp.cleanup)
        self.registry_dir = Path(self.temp.name) / "registry"
        self.path = Path(self.temp.name) / "accounts-local.json"
        self.path.write_text(json.dumps(rows()), encoding="utf-8")
        self.vault = InMemoryTestVault()
        self.out = io.StringIO()
        self.err = io.StringIO()

    def run_cli(self, args):
        with contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.err):
            return main(args, vault_factory=lambda: self.vault, registry_dir=self.registry_dir)

    def assert_output_redacted(self):
        combined = self.out.getvalue() + self.err.getvalue()
        for secret in ("synthetic-token", "synthetic-credential", "@example.test", "refresh_token"):
            self.assertNotIn(secret, combined)

    def test_preview_no_side_effects(self):
        exit_code = self.run_cli(["preview", "--file", str(self.path)])
        self.assertEqual(exit_code, 0)
        result = json.loads(self.out.getvalue())
        self.assertEqual(result["accounts"], 2)
        self.assertFalse(self.registry_dir.exists())
        self.assertEqual(self.vault._values, {})
        self.assert_output_redacted()

    @unittest.skipUnless(os.name == "nt", "Windows-only native workflow")
    def test_import_requires_explicit_confirmation(self):
        exit_code = self.run_cli(["import", "--file", str(self.path)])
        self.assertEqual(exit_code, 3)
        self.assertEqual(self.vault._values, {})
        self.assertFalse(self.registry_dir.exists())
        self.assert_output_redacted()

    @unittest.skipUnless(os.name == "nt", "Windows-only native workflow")
    def test_import_status_and_no_identity_in_output(self):
        self.assertEqual(self.run_cli([
            "import", "--file", str(self.path), "--confirm-local-storage",
        ]), 0)
        self.assertEqual(len(self.vault._values), 2)
        self.assert_output_redacted()
        self.out = io.StringIO()
        self.assertEqual(self.run_cli(["status"]), 0)
        status = json.loads(self.out.getvalue())
        self.assertEqual(status["registered_accounts"], 2)
        self.assertEqual(status["credentials_present"], 2)
        self.assert_output_redacted()

    @unittest.skipUnless(os.name == "nt", "Windows-only native workflow")
    def test_status_on_missing_registry_does_not_create_directory(self):
        self.assertEqual(self.run_cli(["status"]), 0)
        self.assertFalse(self.registry_dir.exists())
        self.assert_output_redacted()

    @unittest.skipUnless(os.name == "nt", "Windows-only native workflow")
    def test_recover_requires_explicit_confirmation(self):
        self.assertEqual(self.run_cli(["recover"]), 3)
        self.assertFalse(self.registry_dir.exists())

    @unittest.skipUnless(os.name == "nt", "Windows-only native workflow")
    def test_bad_file_does_not_echo_payload(self):
        self.path.write_text("synthetic-credential-not-json", encoding="utf-8")
        self.assertEqual(self.run_cli([
            "import", "--file", str(self.path), "--confirm-local-storage",
        ]), 2)
        self.assert_output_redacted()
        self.assertEqual(self.vault._values, {})


if __name__ == "__main__":
    unittest.main()
