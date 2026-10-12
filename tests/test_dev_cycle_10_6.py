"""10.6: no provider calls, no automatic Git push/PR/merge, bounded offline QA handoff."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rai_fabric.store import FabricStore
from rai_fabric import dev_cycle_10_6 as cycle
from rai_fabric import worktree_review as wt


class PureDevelopmentGateTests(unittest.TestCase):
    def test_sha256_stamped_json_readback(self):
        data = cycle._stamp({"x": 1})
        self.assertEqual(cycle._check_stamp(data), {"x": 1})
        with self.assertRaises(cycle.CycleBlocked):
            cycle._check_stamp({**data, "x": 2})

    def test_wrong_receipt_digest_fails(self):
        with self.assertRaisesRegex(cycle.CycleBlocked, "CYCLE_RECEIPT_SEAL_INVALID"):
            cycle._check_stamp({"x": 1, "sha256": "000"})

    def test_duplicate_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name) / "bad.json"
            p.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaisesRegex(cycle.CycleBlocked, "CYCLE_JSON_INVALID"):
                cycle._read_json(p)

    def test_legacy_checkout_spelling_casefold(self):
        self.assertTrue(cycle._is_legacy(r"C:\GIT\Rassvet_AI_Fabric"))
        self.assertTrue(cycle._is_legacy("c:/git/rassvet_ai_fabric/"))
        self.assertFalse(cycle._is_legacy(r"D:\ЗАГРУЗКИ\RAIF_10_6"))

    def test_model_calls_are_not_part_of_mock_contract(self):
        self.assertEqual(cycle.SCHEMA, "RAIF_10_6_OFFLINE_CYCLE/1")
        self.assertNotIn("APPROVED", cycle.CURSOR)


@unittest.skipUnless(sys.platform == "win32", "Windows-owned offline integration")
class WindowsDevelopmentCycleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="raif-10-6-source-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        self._git("init", "-q")
        self._git("config", "user.name", "Synthetic Offline Reviewer")
        self._git("config", "user.email", "synthetic@example.invalid")
        self._git("config", "core.autocrlf", "false")
        (self.repo / "seed.txt").write_text("baseline\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
        self._git("add", "seed.txt", ".gitignore")
        self._git("commit", "-qm", "Initial offline fixture")
        self.pin = self._git("rev-parse", "HEAD").strip()
        self.output = self.root / "runs"
        self.store = FabricStore(self.root / "state.sqlite3", initialize=True)
        self.addCleanup(self.store.close)
        self.store.submit("Only deterministic mock development", "mock", str(self.repo), task_id="dev-1")

    def _git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                                capture_output=True, timeout=18, text=True)
        return result.stdout

    def run_cycle(self):
        return cycle.run_synthetic_cycle(self.store, "dev-1", self.repo,
                                         self.pin, self.output)

    def test_full_cycle_produces_review_intent_no_pr(self):
        out = self.run_cycle()
        self.assertEqual(out["verdict"], "PACKAGE_READY_QA_PENDING")
        self.assertEqual(out["mock_tests_passed"], 3)
        self.assertEqual(out["task_status"], "COMPLETE")
        self.assertFalse(out["pr_created"])
        self.assertFalse(out["merge_authorized"])
        self.assertEqual(self.store.get("dev-1")["checkpoint"]["evidence"]["pr_created"], False)
        self.assertEqual(self._git("rev-parse", "HEAD").strip(), self.pin)
        self.assertEqual(self._git("status", "--porcelain"), "")
        run = Path(out["run_dir"])
        self.assertTrue((run / "REVIEW.patch").is_file())
        self.assertIn(wt.MOCK_PATH, (run / "REVIEW.patch").read_text(encoding="utf-8"))
        qa = json.loads((run / "QA_REQUEST.json").read_text(encoding="utf-8"))
        self.assertEqual(qa["actual_independent_review"], "NOT_PERFORMED")
        draft = json.loads((run / "DRAFT_PR_INTENT.json").read_text(encoding="utf-8"))
        self.assertFalse(draft["publication_authorized"])
        self.assertFalse(draft["merge_authorized"])
        verify = cycle.verify_cycle_receipt(run)
        self.assertEqual(verify["verdict"], "READBACK_PASS_QA_PENDING")
        self.assertEqual(verify["patch_sha256"], out["patch_sha256"])

    def test_no_replay_after_completed_task(self):
        self.run_cycle()
        with self.assertRaisesRegex(cycle.CycleBlocked, "NON_SYNTHETIC_OR_CLAIMED_TASK"):
            self.run_cycle()
        self.assertEqual(self.store.get("dev-1")["attempt"], 1)

    def test_wrong_pin_rejected_before_claim(self):
        with self.assertRaises(wt.ReviewBlocked):
            cycle.run_synthetic_cycle(self.store, "dev-1", self.repo, "0"*40, self.output)
        self.assertEqual(self.store.get("dev-1")["status"], "QUEUED")
        self.assertFalse(self.output.exists())

    def test_external_provider_refused_before_any_claim(self):
        self.store.submit("Not allowed real", "antigravity", str(self.repo), task_id="external")
        with self.assertRaisesRegex(cycle.CycleBlocked, "NON_SYNTHETIC_OR_CLAIMED_TASK"):
            cycle.run_synthetic_cycle(self.store, "external", self.repo, self.pin, self.output)
        self.assertEqual(self.store.get("external")["status"], "QUEUED")
        self.assertEqual(self.store.get("external")["attempt"], 0)

    def test_bad_owner_rejected_preclaim(self):
        with self.assertRaisesRegex(cycle.CycleBlocked, "EXECUTOR_OWNER_INVALID"):
            cycle.run_synthetic_cycle(self.store, "dev-1", self.repo, self.pin,
                                      self.output, owner="owner with spaces")
        self.assertEqual(self.store.get("dev-1")["attempt"], 0)

    def test_dirty_source_rejected_before_claim(self):
        (self.repo / "untracked.txt").write_text("uncommitted", encoding="utf-8")
        with self.assertRaisesRegex(cycle.CycleBlocked, "SOURCE_REPOSITORY_DIRTY"):
            self.run_cycle()
        self.assertEqual(self.store.get("dev-1")["attempt"], 0)
        self.assertFalse(self.output.exists())

    def test_blocked_dependencies_do_not_claim_or_mutate(self):
        self.store.submit("First", "mock", str(self.repo), task_id="dependency")
        self.store.submit("Second", "mock", str(self.repo), task_id="blocked-dep",
                          depends_on=["dependency"])
        with self.assertRaisesRegex(cycle.CycleBlocked, "DEVELOPMENT_TASK_NOT_READY"):
            cycle.run_synthetic_cycle(self.store, "blocked-dep", self.repo, self.pin, self.output)
        self.assertEqual(self.store.get("blocked-dep")["status"], "QUEUED")
        self.assertEqual(self.store.get("blocked-dep")["attempt"], 0)

    def test_task_workspace_mismatch_refused(self):
        other = self.root / "second"
        other.mkdir()
        self.store.submit("Different repo", "mock", str(other), task_id="different")
        with self.assertRaisesRegex(cycle.CycleBlocked, "TASK_REPOSITORY_MISMATCH"):
            cycle.run_synthetic_cycle(self.store, "different", self.repo, self.pin, self.output)
        self.assertEqual(self.store.get("different")["status"], "QUEUED")

    def test_output_overlaps_source_blocked(self):
        with self.assertRaises(cycle.CycleBlocked):
            cycle.run_synthetic_cycle(self.store, "dev-1", self.repo,
                                      self.pin, self.repo / "subfolder")
        self.assertEqual(self.store.get("dev-1")["attempt"], 0)

    def test_database_inside_source_blocked(self):
        with FabricStore(self.repo / "inside.db", initialize=True) as inside:
            inside.submit("Unsafe", "mock", str(self.repo), task_id="inside")
            with self.assertRaisesRegex(cycle.CycleBlocked, "QUEUE_DB_ISOLATION_REQUIRED"):
                cycle.run_synthetic_cycle(inside, "inside", self.repo, self.pin, self.output)
            self.assertEqual(inside.get("inside")["attempt"], 0)

    def test_blocked_review_is_terminal_no_retry(self):
        with patch.object(cycle.wt, "offline_demo", side_effect=wt.ReviewBlocked("OUT_OF_ALLOWLIST")):
            with self.assertRaisesRegex(cycle.CycleBlocked, "OUT_OF_ALLOWLIST"):
                self.run_cycle()
        self.assertEqual(self.store.get("dev-1")["status"], "BLOCKED")
        self.assertEqual(self.store.get("dev-1")["attempt"], 1)
        self.assertFalse(self.output.exists())

    def test_manifest_tamper_blocks_readback(self):
        run = Path(self.run_cycle()["run_dir"])
        manifest = run / "MANIFEST.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["allowlist"] = ["unapproved.py"]
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(wt.ReviewBlocked):
            cycle.verify_cycle_receipt(run)

    def test_patch_tamper_blocks_readback(self):
        run = Path(self.run_cycle()["run_dir"])
        patch_path = run / "REVIEW.patch"
        patch_path.write_bytes(patch_path.read_bytes() + b"\nATTACK\n")
        with self.assertRaisesRegex(cycle.CycleBlocked, "SOURCE_OR_PATCH_SHA_DRIFT"):
            cycle.verify_cycle_receipt(run)

    def test_sidecar_artifact_tamper_blocks_readback(self):
        run = Path(self.run_cycle()["run_dir"])
        qa_file = run / "QA_REQUEST.json"
        data = json.loads(qa_file.read_text(encoding="utf-8"))
        data["actual_independent_review"] = "PASS"
        qa_file.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(cycle.CycleBlocked):
            cycle.verify_cycle_receipt(run)

    def test_fake_external_receipt_cannot_promote(self):
        run = Path(self.run_cycle()["run_dir"])
        (run / "FAKE_QA.json").write_text('{"verdict":"PASS"}', encoding="utf-8")
        read = cycle.verify_cycle_receipt(run)
        self.assertEqual(read["independent_qa"], "NOT_PERFORMED")
        self.assertFalse(read["publication_authorized"])
        self.assertFalse(read["merge_authorized"])

    def test_missing_draft_artifact_blocks_readback(self):
        run = Path(self.run_cycle()["run_dir"])
        (run / "DRAFT_PR_INTENT.json").unlink()
        with self.assertRaises(cycle.CycleBlocked):
            cycle.verify_cycle_receipt(run)

    def test_source_modified_after_stage_blocks_readback(self):
        run = Path(self.run_cycle()["run_dir"])
        (self.repo / "seed.txt").write_text("tampered source\n", encoding="utf-8")
        with self.assertRaisesRegex(cycle.CycleBlocked, "SOURCE_REPOSITORY_DIRTY"):
            cycle.verify_cycle_receipt(run)


if __name__ == "__main__":
    unittest.main()
