"""Windows-only acceptance and negative tests for offline worktree review (RAiF 10.1)."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rai_fabric.worktree_review import (
    MOCK_PATH, NEXT_WINDOWS, ReviewBlocked, _allowed, _assert_local_volume,
    main, offline_demo,
    prepare, review,
)


@unittest.skipUnless(sys.platform == "win32", "Windows-only acceptance suite")
class OfflineWorktreeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="raif-worktree-10-1-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        self._git("init", "-q")
        self._git("config", "user.name", "Offline Test")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "core.autocrlf", "false")
        (self.repo / "seed.txt").write_text("baseline\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
        self._git("add", "seed.txt", ".gitignore")
        self._git("commit", "-qm", "Baseline")
        self.pin = self._git("rev-parse", "HEAD").strip()
        self.out = self.root / "results"

    def _git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo), *args],
                                check=True, capture_output=True, text=True,
                                timeout=20)
        return result.stdout

    def _prepare(self, allowed=None):
        return prepare(self.repo, self.pin, self.out, allowed or [MOCK_PATH])

    @staticmethod
    def _put(run: Path, name: str, contents: bytes):
        path = run / "workspace" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    @staticmethod
    def _code(exc):
        return exc.exception.code

    def test_exact_pin_and_three_mock_tests_without_live_turn(self):
        result = offline_demo(self.repo, self.pin, self.out)
        self.assertEqual(result["verdict"], "PENDING_HUMAN_APPROVAL")
        self.assertEqual(result["cursor"], NEXT_WINDOWS)
        self.assertEqual(result["mock_tests_passed"], 3)
        self.assertEqual(self._git("rev-parse", "HEAD").strip(), self.pin)
        self.assertEqual(self._git("status", "--porcelain"), "")
        run = Path(result["run_dir"])
        self.assertTrue((run / "REVIEW.patch").is_file())
        self.assertIn("sandbox_demo/arithmetic.py", (run / "REVIEW.patch").read_text("utf-8"))
        checkpoint = json.loads((run / "CHECKPOINT.json").read_text("utf-8"))
        self.assertEqual(checkpoint["model_turn_count"], 0)
        self.assertEqual(checkpoint["git_push_count"], 0)
        self.assertEqual(checkpoint["git_merge_count"], 0)
        self.assertEqual(checkpoint["verdict"], "PENDING_HUMAN_APPROVAL")
        self.assertEqual(self._git("worktree", "list", "--porcelain").count("detached\n"), 1)

    def test_prepare_does_not_modify_source(self):
        run = self._prepare(["scratch/safe.py"])
        self.assertEqual(self._git("status", "--porcelain"), "")
        manifest = json.loads((run / "MANIFEST.json").read_text("utf-8"))
        self.assertEqual(manifest["pin_sha"], self.pin)
        self.assertEqual(manifest["allowlist"], ["scratch/safe.py"])
        self.assertTrue((run / "workspace" / ".git").is_file())
        self.assertFalse((run / "REVIEW.patch").exists())

    def test_generic_text_review_only_without_untrusted_tests(self):
        run = self._prepare(["scratch/safe.py"])
        self._put(run, "scratch/safe.py", b"value = 5\n")
        result = review(run)
        self.assertEqual(result["mock_tests_passed"], 0)
        self.assertEqual(result["verdict"], "PENDING_HUMAN_APPROVAL")
        self.assertTrue((run / "REVIEW.patch").exists())

    def test_bad_commit_pin_blocked_before_worktree_creation(self):
        with self.assertRaises(ReviewBlocked) as raised:
            prepare(self.repo, "0" * 40, self.out, [MOCK_PATH])
        self.assertEqual(self._code(raised), "SOURCE_HEAD_NOT_PINNED")
        self.assertFalse(self.out.exists())

    def test_outside_allowlist_blocked(self):
        run = self._prepare()
        self._put(run, "scratch/unauthorized.py", b"value = 1\n")
        with self.assertRaises(ReviewBlocked) as raised:
            review(run)
        self.assertEqual(self._code(raised), "OUT_OF_ALLOWLIST")
        self.assertFalse((run / "REVIEW.patch").exists())

    def test_extra_changed_file_blocked_even_if_expected_file_present(self):
        run = self._prepare()
        self._put(run, MOCK_PATH, b"def add(a, b):\n    return a + b\n")
        self._put(run, "scratch/extra.txt", b"no\n")
        with self.assertRaises(ReviewBlocked):
            review(run)

    def test_secret_pattern_blocked_and_patch_never_saved(self):
        run = self._prepare()
        self._put(run, MOCK_PATH, b"key = 'sk-" + b"x" * 28 + b"'\n")
        with self.assertRaises(ReviewBlocked) as raised:
            review(run)
        self.assertEqual(self._code(raised), "POTENTIAL_SECRET_BLOCKED")
        self.assertFalse((run / "REVIEW.patch").exists())

    def test_binary_change_blocked(self):
        run = self._prepare()
        self._put(run, MOCK_PATH, b"abc\x00def")
        with self.assertRaises(ReviewBlocked) as raised:
            review(run)
        self.assertEqual(self._code(raised), "BINARY_OR_FILE_SIZE_BLOCKED")

    def test_too_large_file_blocked(self):
        run = self._prepare()
        self._put(run, MOCK_PATH, b"a" * (128 * 1024 + 1))
        with self.assertRaises(ReviewBlocked) as raised:
            review(run)
        self.assertEqual(self._code(raised), "FILE_SIZE_LIMIT")

    def test_delete_tracked_file_blocked(self):
        run = self._prepare(["seed.txt"])
        (run / "workspace" / "seed.txt").unlink()
        with self.assertRaises(ReviewBlocked) as raised:
            review(run)
        self.assertEqual(self._code(raised), "UNSUPPORTED_GIT_CHANGE")

    def test_staged_git_index_change_blocked(self):
        run = self._prepare(["seed.txt"])
        self._put(run, "seed.txt", b"changed\n")
        subprocess.run(["git", "-C", str(run / "workspace"), "add", "seed.txt"],
                       check=True, capture_output=True, timeout=20)
        with self.assertRaises(ReviewBlocked) as raised:
            review(run)
        self.assertEqual(self._code(raised), "INDEX_MUTATION_BLOCKED")
        self.assertFalse((run / "REVIEW.patch").exists())

    def test_ignored_untracked_file_blocked(self):
        run = self._prepare(["scratch/safe.py"])
        self._put(run, "scratch/safe.py", b"value = 1\n")
        self._put(run, "scratch/generated.pyc", b"ignored")
        with self.assertRaises(ReviewBlocked) as raised:
            review(run)
        self.assertEqual(self._code(raised), "IGNORED_FILES_PRESENT")

    def test_incorrect_offline_mock_source_fails_3_tests(self):
        run = self._prepare()
        self._put(run, MOCK_PATH, b"def add(a, b):\n    return a - b\n")
        with self.assertRaises(ReviewBlocked) as raised:
            review(run, run_mock_tests=True)
        self.assertEqual(self._code(raised), "MOCK_SOURCE_NOT_IDENTICAL")

    def test_mode_dependent_forbidden_paths(self):
        for value in ("../out.py", ".git/config", "CKS/canon.txt", ".github/workflows/x.yml",
                      "readme.md", "C:/Windows/test", "foo:stream", "a\\b", "con.py"):
            with self.subTest(value=value), self.assertRaises(ReviewBlocked):
                _allowed([value])
        with self.assertRaises(ReviewBlocked) as raised:
            _allowed(["a/File.py", "a/file.py"])
        self.assertEqual(self._code(raised), "ALLOWLIST_CASE_COLLISION")

    def test_unc_paths_blocked_for_offline_guarantee(self):
        with self.assertRaises(ReviewBlocked) as raised:
            _assert_local_volume(Path(r"\\server\share\work"))
        self.assertEqual(self._code(raised), "LOCAL_DRIVE_REQUIRED")

    def test_link_target_blocked_if_symlink_available(self):
        run = self._prepare(["scratch/linked.py"])
        outside = self.root / "outside.py"
        outside.write_text("secret = 1\n", encoding="utf-8")
        link = run / "workspace" / "scratch" / "linked.py"
        link.parent.mkdir()
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("Windows symlink creation requires local privilege")
        with self.assertRaises(ReviewBlocked) as raised:
            review(run)
        self.assertIn(self._code(raised), ("REPARSE_POINT_BLOCKED", "UNSUPPORTED_GIT_CHANGE"))

    def test_manifest_tampering_rejected(self):
        run = self._prepare()
        doc = json.loads((run / "MANIFEST.json").read_text("utf-8"))
        doc["allowlist"] = ["scratch/bypass.py"]
        (run / "MANIFEST.json").write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(ReviewBlocked) as raised:
            review(run)
        self.assertEqual(self._code(raised), "MANIFEST_INTEGRITY_FAILURE")

    def test_review_cli_creates_blocked_checkpoint_without_secret(self):
        run = self._prepare()
        self._put(run, "scratch/not_permitted.py", b"bad\n")
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            rc = main(["review", "--run", str(run)])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(captured.getvalue())["verdict"], "BLOCKED")
        doc = json.loads((run / "CHECKPOINT.json").read_text("utf-8"))
        self.assertEqual(doc["verdict"], "BLOCKED")
        self.assertIn("OUT_OF_ALLOWLIST", (run / "STAGES.jsonl").read_text("utf-8"))

    def test_no_auto_run_any_user_supplied_test_code(self):
        run = self._prepare(["scratch/only.py"])
        self._put(run, "scratch/only.py", b"raise Exception('do not execute')\n")
        result = review(run)
        self.assertEqual(result["mock_tests_passed"], 0)
        self.assertEqual(result["verdict"], "PENDING_HUMAN_APPROVAL")

    def test_prevent_checkout_filters(self):
        (self.repo / ".gitattributes").write_text("* filter=evil\n", encoding="utf-8")
        self._git("add", ".gitattributes")
        self._git("commit", "-qm", "Filtered snapshot")
        pin = self._git("rev-parse", "HEAD").strip()
        with self.assertRaises(ReviewBlocked) as raised:
            prepare(self.repo, pin, self.out, [MOCK_PATH])
        self.assertEqual(self._code(raised), "CHECKOUT_ATTR_OR_SUBMODULE_BLOCKED")


if __name__ == "__main__":
    unittest.main()
