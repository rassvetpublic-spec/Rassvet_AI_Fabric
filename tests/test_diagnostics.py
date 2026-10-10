import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raif_ag_supervisor.diagnostics import readonly_status
from raif_ag_supervisor.registry import LocalAccountRegistry
from raif_ag_supervisor.session_probe import ProcessIdentity
from raif_ag_supervisor.vault import InMemoryTestVault
from raif_ag_supervisor.__main__ import main


class DiagnosticTests(unittest.TestCase):
    def test_missing_registry_read_only(self):
        with tempfile.TemporaryDirectory() as base:
            missing = Path(base) / "unconfigured"
            result = readonly_status(missing, probe=lambda: ())
            self.assertFalse(result["registry_configured"])
            self.assertEqual(result["registered_accounts"], 0)
            self.assertFalse(missing.exists())

    def test_report_contains_no_emails_tokens_or_account_ids(self):
        with tempfile.TemporaryDirectory() as base:
            registry = LocalAccountRegistry(Path(base))
            vault = InMemoryTestVault()
            accounts = [
                {"email": "someone@example.test", "refresh_token": "synthetic-one"}
            ]
            ids = registry.import_manifest(json.dumps(accounts).encode("utf-8"), vault)
            result = readonly_status(
                Path(base), probe=lambda: (ProcessIdentity("antigravity.exe", 123),)
            )
            display = json.dumps(result)
            self.assertEqual(result["registered_accounts"], 1)
            self.assertEqual(result["processes"][0]["pid"], 123)
            self.assertNotIn(ids[0], display)
            self.assertNotIn("example.test", display)
            self.assertNotIn("synthetic-one", display)
            self.assertFalse(result["session_authorization_verified"])
            self.assertFalse(result["hot_swap_verified"])

    def test_pending_journal_is_visible_as_boolean_only(self):
        with tempfile.TemporaryDirectory() as base:
            registry = LocalAccountRegistry(Path(base))
            registry.pending_path.write_text('{"version":1,"allocated":[]}')
            result = readonly_status(Path(base), probe=lambda: ())
            self.assertTrue(result["recovery_required"])
            self.assertNotIn("allocated", json.dumps(result))

    def test_cli_status_serializes_only_sanitized_report(self):
        fake = {
            "platform": "windows", "registry_configured": False,
            "registered_accounts": 0, "recovery_required": False,
            "processes": [], "session_authorization_verified": False,
            "hot_swap_verified": False,
        }
        stdout = io.StringIO()
        with patch("raif_ag_supervisor.__main__.readonly_status", return_value=fake):
            with contextlib.redirect_stdout(stdout):
                result = main(["status", "--registry-dir", "./synthetic-only"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout.getvalue()), fake)


if __name__ == "__main__":
    unittest.main()
