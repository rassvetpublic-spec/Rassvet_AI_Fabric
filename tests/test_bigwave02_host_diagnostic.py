"""New BIGWAVE 02 negative coverage: no model, network, credentials or Git writes."""
import subprocess
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rai_fabric import host_diagnostic_10_3 as h


class HostDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="raif-host-diag-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "source"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / ".git" / "config").write_text("[core]\n", encoding="ascii")
        self.git = self.root / "git.exe"
        self.git.write_bytes(b"MOCK_EXECUTABLE_NOT_RUN")
        self.mock_sha = hashlib.sha256(self.git.read_bytes()).hexdigest()
        sha_patch = patch.object(h, "_WINDOWS_GIT_SHA256", self.mock_sha)
        sha_patch.start()
        self.addCleanup(sha_patch.stop)

    def inspect_mock(self, probes):
        with patch.object(h, "_WINDOWS_GIT_CMD", self.git), \
                patch.object(h.shutil, "which", return_value=str(self.git)), \
                patch.object(h, "_invoke_git", side_effect=probes) as invoke:
            report = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(report["git_reads"], invoke.call_count)
        self.assertEqual(report["network_calls"], 0)
        self.assertEqual(report["source_mutations"], 0)
        self.assertFalse(report["host_qa_verified"])
        self.assertFalse(report["credentials_read"])
        return report

    def test_exact_main_is_only_prefight(self):
        report = self.inspect_mock([h.Probe("OK", str(self.repo)),
            h.Probe("OK", sorted(h._ORIGINS)[0]), h.Probe("OK", h.MAIN_SHA),
            h.Probe("OK", ""), h.Probe("OK", ""), h.Probe("OK", h.MAIN_SHA)])
        self.assertEqual(report["verdict"], "HOST_MAIN_10_3_CLEAN_PREFLIGHT_ONLY")
        self.assertEqual(report["source_class"], "MAIN_10_3_EXACT")
        self.assertEqual(report["git_reads"], 6)
        self.assertFalse(report["merge_authorized"])

    def test_old_pin_is_never_upgraded_to_main(self):
        report = self.inspect_mock([h.Probe("OK", str(self.repo)),
            h.Probe("OK", sorted(h._ORIGINS)[0]), h.Probe("OK", h.LEGACY_10_1_SHA),
            h.Probe("OK", ""), h.Probe("OK", ""), h.Probe("OK", h.LEGACY_10_1_SHA)])
        self.assertEqual(report["verdict"], "HOST_KNOWN_LEGACY_PIN_CLEAN_NO_UPDATE")
        self.assertEqual(report["source_class"], "LEGACY_10_1_EXACT")

    def test_stale_ag_pin_does_not_count_as_main(self):
        report = self.inspect_mock([h.Probe("OK", str(self.repo)),
            h.Probe("OK", sorted(h._ORIGINS)[0]), h.Probe("OK", h.AG_BASE_SHA),
            h.Probe("OK", ""), h.Probe("OK", ""), h.Probe("OK", h.AG_BASE_SHA)])
        self.assertEqual(report["source_class"], "AG_PATHER_PREVIOUS_EXACT")
        self.assertFalse(report["host_qa_verified"])

    def test_unknown_head_blocks_early(self):
        report = self.inspect_mock([h.Probe("OK", str(self.repo)),
            h.Probe("OK", sorted(h._ORIGINS)[0]), h.Probe("OK", "f" * 40)])
        self.assertEqual(report["verdict"], "HOST_HEAD_NOT_KNOWN")
        self.assertEqual(report["git_reads"], 3)

    def test_safe_directory_reason_fixed_and_redacted(self):
        report = self.inspect_mock([h.Probe("GIT_SAFE_DIRECTORY_REJECTED")])
        self.assertEqual(report["verdict"], "HOST_ROOT_GIT_SAFE_DIRECTORY_REJECTED")
        self.assertEqual(report["git_reads"], 1)

    def test_git_exit_unknown_does_not_emit_untrusted_error(self):
        sensitive = b"FATAL private id ref-token VALUE_123456\n"
        self.assertEqual(h._classify_git_stderr(sensitive), "GIT_COMMAND_REJECTED")
        self.assertEqual(h._classify_git_stderr(b"fatal: detected dubious ownership in repository"),
                         "GIT_SAFE_DIRECTORY_REJECTED")
        self.assertEqual(h._classify_git_stderr(b"error: Access is denied"), "GIT_ACCESS_DENIED")
        self.assertEqual(h._classify_git_stderr(b"fatal: not a git repository"), "GIT_NOT_REPOSITORY")

    def test_missing_git_folder_is_not_authority_to_clone(self):
        import shutil
        shutil.rmtree(self.repo / ".git")
        report = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(report["verdict"], "HOST_GIT_DIRECTORY_MISSING")
        self.assertEqual(report["git_reads"], 0)

    def test_missing_repo_is_safely_reported(self):
        report = h.inspect_clone(self.root / "no-repo", windows_override_for_tests=True)
        self.assertEqual(report["verdict"], "HOST_DIRECTORY_MISSING")

    def test_checkout_ref_moves_during_probe_blocks(self):
        report = self.inspect_mock([h.Probe("OK", str(self.repo)),
            h.Probe("OK", sorted(h._ORIGINS)[0]), h.Probe("OK", h.MAIN_SHA),
            h.Probe("OK", ""), h.Probe("OK", ""), h.Probe("OK", "f" * 40)])
        self.assertEqual(report["verdict"], "HOST_HEAD_MOVED_DURING_PROBE")
        self.assertFalse(report["host_qa_verified"])

    def test_config_symlink_or_junction_does_not_trigger_git(self):
        original = h._unsafe_ancestor
        def fake(path):
            return path == self.repo / ".git" / "config" or original(path)
        with patch.object(h, "_unsafe_ancestor", side_effect=fake), \
                patch.object(h, "_invoke_git") as fn:
            report = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(report["verdict"], "HOST_GIT_CONFIG_REPARSE_BLOCKED")
        fn.assert_not_called()

    def test_gitfile_worktree_does_not_trigger_a_checkout(self):
        import shutil
        shutil.rmtree(self.repo / ".git")
        (self.repo / ".git").write_text("gitdir: secrets/hidden\n")
        report = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(report["verdict"], "HOST_WORKTREE_GITFILE_UNSUPPORTED")
        self.assertEqual(report["git_reads"], 0)

    def test_origin_with_credentials_is_not_returned(self):
        report = self.inspect_mock([h.Probe("OK", str(self.repo)),
            h.Probe("OK", "https://user:supersecret@github.com/rassvetpublic-spec/Rassvet_AI_Fabric.git")])
        self.assertEqual(report["verdict"], "HOST_ORIGIN_UNEXPECTED")
        self.assertNotIn("supersecret", str(report))

    def test_root_mismatch_blocks(self):
        report = self.inspect_mock([h.Probe("OK", str(self.root))])
        self.assertEqual(report["verdict"], "HOST_ROOT_MISMATCH")

    def test_dirty_and_ignored_statuses_are_distinct(self):
        prefix = [h.Probe("OK", str(self.repo)), h.Probe("OK", sorted(h._ORIGINS)[0]),
                  h.Probe("OK", h.MAIN_SHA)]
        dirty = self.inspect_mock(prefix + [h.Probe("OK", " M src/fake.py")])
        ignored = self.inspect_mock(prefix + [h.Probe("OK", ""), h.Probe("OK", "hidden/ignored")])
        self.assertEqual(dirty["verdict"], "HOST_WORKTREE_NOT_CLEAN")
        self.assertEqual(ignored["verdict"], "HOST_IGNORED_FILES_PRESENT")
        self.assertEqual(dirty["git_reads"], 4)
        self.assertEqual(ignored["git_reads"], 5)

    def test_git_executable_path_is_checked(self):
        with patch.object(h, "_WINDOWS_GIT_CMD", self.root / "not-installed-git.exe"), \
                patch.object(h.shutil, "which", return_value=None):
            report = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(report["verdict"], "GIT_EXECUTABLE_MISSING")

    def test_pinned_windows_git_used_when_not_in_path(self):
        probes = [h.Probe("OK", str(self.repo)),
                  h.Probe("OK", sorted(h._ORIGINS)[0]),
                  h.Probe("OK", h.MAIN_SHA),
                  h.Probe("OK", ""), h.Probe("OK", ""), h.Probe("OK", h.MAIN_SHA)]
        with patch.object(h, "_WINDOWS_GIT_CMD", self.git), \
                patch.object(h.shutil, "which", return_value=None) as which, \
                patch.object(h, "_invoke_git", side_effect=probes) as invoke:
            report = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(report["verdict"], "HOST_MAIN_10_3_CLEAN_PREFLIGHT_ONLY")
        self.assertEqual(report["git_reads"], 6)
        which.assert_not_called()
        self.assertEqual([c.args[1] for c in invoke.call_args_list],
                         [str(self.git)] * 6)

    def test_pinned_windows_git_preferred_over_path_match(self):
        other = self.root / "unexpected-git.exe"
        other.write_bytes(b"NOT_EXECUTABLE")
        with patch.object(h, "_WINDOWS_GIT_CMD", self.git), \
                patch.object(h.shutil, "which", return_value=str(other)) as which, \
                patch.object(h, "_invoke_git", return_value=h.Probe("GIT_TIMEOUT")) as invoke:
            report = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(report["verdict"], "HOST_ROOT_GIT_TIMEOUT")
        self.assertEqual(invoke.call_args.args[1], str(self.git))
        which.assert_not_called()

    def test_pinned_windows_git_with_unsafe_reparse_is_blocked(self):
        def unsafe(path):
            return path == self.git
        with patch.object(h, "_WINDOWS_GIT_CMD", self.git), \
                patch.object(h.shutil, "which", return_value=None), \
                patch.object(h, "_unsafe_ancestor", side_effect=unsafe), \
                patch.object(h, "_invoke_git") as invoke:
            report = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(report["verdict"], "GIT_EXECUTABLE_UNSAFE")
        invoke.assert_not_called()

    def test_pinned_git_inside_inspected_checkout_is_rejected(self):
        local_git = self.repo / "bin" / "git.exe"
        local_git.parent.mkdir()
        local_git.write_bytes(b"NOT_EXECUTABLE")
        with patch.object(h, "_WINDOWS_GIT_CMD", local_git), \
                patch.object(h.shutil, "which", return_value=None), \
                patch.object(h, "_invoke_git") as invoke:
            report = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(report["verdict"], "GIT_EXECUTABLE_UNTRUSTED")
        invoke.assert_not_called()

    def test_git_command_scrubs_sensitive_env_and_never_uses_shell(self):
        def capture(argv, env, timeout_seconds=8.0):
            self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")
            self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
            self.assertEqual(env["GIT_LFS_SKIP_SMUDGE"], "1")
            self.assertNotIn("GIT_TRACE", env)
            self.assertIn("credential.helper=", argv)
            self.assertIn("protocol.ext.allow=never", argv)
            self.assertEqual(argv[-2:], ["rev-parse", "--show-toplevel"])
            self.assertEqual(argv[0], str(self.git))
            return h.Probe("GIT_SAFE_DIRECTORY_REJECTED")
        with patch.dict(h.os.environ, {"GIT_TRACE": "1", "SECRET_ENV": "DO_NOT_PRINT"}), \
                patch.object(h, "_capture_bounded", side_effect=capture):
            result = h._invoke_git(self.repo, str(self.git), ("rev-parse", "--show-toplevel"))
        self.assertEqual(result.status, "GIT_SAFE_DIRECTORY_REJECTED")
        self.assertNotIn("secret", repr(result))

    def test_actual_bounded_pipe_overflow_stops_4mb_child(self):
        command = [sys.executable, "-I", "-B", "-c",
                   "import sys;sys.stdout.buffer.write(b'X'*4194304);sys.stdout.flush()"]
        result = h._capture_bounded(command, os.environ.copy(), timeout_seconds=5)
        self.assertEqual(result.status, "GIT_OUTPUT_BOUNDED_ABORT")
        self.assertNotIn("X" * 256, repr(result))

    def test_actual_bounded_pipe_timeout(self):
        command = [sys.executable, "-I", "-B", "-c", "import time;time.sleep(4)"]
        result = h._capture_bounded(command, os.environ.copy(), timeout_seconds=0.15)
        self.assertEqual(result.status, "GIT_TIMEOUT")

    def test_actual_bounded_nonzero_child_error_redacted(self):
        command = [sys.executable, "-I", "-B", "-c",
                   "import sys;sys.stderr.write('SECRET_PRIVATE_VALUE');sys.exit(2)"]
        result = h._capture_bounded(command, os.environ.copy(), timeout_seconds=5)
        self.assertEqual(result.status, "GIT_COMMAND_REJECTED")
        self.assertNotIn("SECRET_PRIVATE_VALUE", repr(result))

    def test_fake_git_on_path_never_executed(self):
        fake = self.root / "untrusted-git.exe"
        fake.write_bytes(b"NO_TRUST")
        with patch.object(h, "_WINDOWS_GIT_CMD", self.root / "missing-git.exe"), \
                patch.object(h.shutil, "which", return_value=str(fake)) as which, \
                patch.object(h, "_invoke_git") as invoke:
            result = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(result["verdict"], "GIT_EXECUTABLE_MISSING")
        which.assert_not_called()
        invoke.assert_not_called()

    def test_wrong_pinned_git_hash_never_executed(self):
        with patch.object(h, "_WINDOWS_GIT_CMD", self.git), \
                patch.object(h, "_WINDOWS_GIT_SHA256", "0" * 64), \
                patch.object(h, "_invoke_git") as invoke:
            result = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(result["verdict"], "GIT_EXECUTABLE_HASH_MISMATCH")
        invoke.assert_not_called()

    def test_reparse_source_fails_before_git(self):
        with patch.object(h, "_unsafe_ancestor", return_value=True), \
                patch.object(h, "_invoke_git") as fn:
            report = h.inspect_clone(self.repo, windows_override_for_tests=True)
        self.assertEqual(report["verdict"], "HOST_REPARSE_OR_PERMISSION_BLOCKED")
        fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
