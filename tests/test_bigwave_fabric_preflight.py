"""Fabric 10.1B safe readback; no clone, network or Git operations in tests."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rai_fabric.host_gate_10_1b import PIN, inspect_fabric_clone, _git


class FabricGateTests(unittest.TestCase):
    def test_no_host_or_invalid_clone_fails_closed(self):
        with tempfile.TemporaryDirectory() as path:
            report = inspect_fabric_clone(Path(path),windows_override_for_tests=True)
        self.assertEqual(report["verdict"],"HOST_CLONE_NOT_PRESENT_OR_NONSTANDARD")
        self.assertFalse(report["full_10_1b_acceptance_verified"])

    def test_wrong_head_blocked_without_mutation(self):
        with tempfile.TemporaryDirectory() as path:
            p=Path(path)
            (p/".git").mkdir()
            responses=iter((str(p), "https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric.git", "f"*40))
            with patch("rai_fabric.host_gate_10_1b._git",side_effect=lambda *args:next(responses)):
                report=inspect_fabric_clone(p,windows_override_for_tests=True)
            self.assertEqual(report["verdict"],"HOST_HEAD_NOT_PINNED_NO_MUTATION")

    def test_exact_pin_preflight_does_not_claim_host_acceptance(self):
        with tempfile.TemporaryDirectory() as path:
            p=Path(path)
            (p/".git").mkdir()
            answers=iter((str(p),"https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric.git",PIN,"",""))
            with patch("rai_fabric.host_gate_10_1b._git",side_effect=lambda *args:next(answers)):
                report=inspect_fabric_clone(p,windows_override_for_tests=True)
            self.assertEqual(report["verdict"],"HOST_PIN_READONLY_PREFLIGHT_PASS")
            self.assertFalse(report["targeted_20_tests_executed"])
            self.assertEqual(report["source_mutations"],0)

    def test_wrong_origin_blocked(self):
        with tempfile.TemporaryDirectory() as path:
            p=Path(path)
            (p/".git").mkdir()
            with patch("rai_fabric.host_gate_10_1b._git",side_effect=[str(p),"https://attacker.example/x"]):
                report=inspect_fabric_clone(p,windows_override_for_tests=True)
            self.assertEqual(report["verdict"],"HOST_ORIGIN_NOT_PINNED")

    def test_dirty_checkout_blocked(self):
        with tempfile.TemporaryDirectory() as path:
            p=Path(path)
            (p/".git").mkdir()
            with patch("rai_fabric.host_gate_10_1b._git",side_effect=[str(p),
                "https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric.git",PIN," M src/file.py"]):
                report=inspect_fabric_clone(p,windows_override_for_tests=True)
            self.assertEqual(report["verdict"],"HOST_CLONE_UNCLEAN_OR_STATUS_FAILED")

    def test_symlink_clone_refused_if_supported(self):
        with tempfile.TemporaryDirectory() as path:
            root=Path(path)
            d=root/"dir";d.mkdir()
            link=root/"link"
            try:link.symlink_to(d,target_is_directory=True)
            except (OSError,NotImplementedError):self.skipTest("symlink permission unavailable")
            report=inspect_fabric_clone(link,windows_override_for_tests=True)
            self.assertEqual(report["verdict"],"HOST_PATH_UNSAFE")

    def test_git_child_is_credentialless_and_nofetch(self):
        class Result:
            returncode=0
            stdout=b"done\n"
        def capture(args,**kw):
            self.assertFalse(kw["shell"])
            self.assertEqual(kw["env"]["GIT_TERMINAL_PROMPT"],"0")
            self.assertEqual(kw["env"]["GIT_NO_LAZY_FETCH"],"1")
            self.assertEqual(kw["env"]["GIT_OPTIONAL_LOCKS"],"0")
            self.assertIn("--no-optional-locks",args)
            self.assertEqual(args[-2:],("rev-parse","HEAD"))
            return Result()
        with patch("rai_fabric.host_gate_10_1b.subprocess.run",side_effect=capture):
            self.assertEqual(_git(Path("."),"rev-parse","HEAD"),"done")

    def test_non_windows_entry_requires_explicit_test_mode(self):
        if sys.platform!="win32":
            report=inspect_fabric_clone(Path("."))
            self.assertEqual(report["verdict"],"WINDOWS_ONLY")


if __name__=="__main__":
    unittest.main()
