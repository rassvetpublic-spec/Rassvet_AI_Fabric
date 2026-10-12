"""Adversarial CP54D cases: uncertain effects never become executable actions."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raif_ag_supervisor import continuity as c


class ContinuityFaultsTests(unittest.TestCase):
    def record(self, generation=0, effect=c.SideEffect.NONE):
        return c.ContinuityRecord("task-012345abcdef", "a" * 40,
                                  "BIGWAVE_02/RECOVERY", generation, effect)

    def encode_raw(self, payload):
        raw = c._canonical(payload)
        outer = {"payload": payload, "sha256": hashlib.sha256(raw).hexdigest()}
        return c._canonical(outer)

    def test_sha_integrity_not_cryptographic_authority(self):
        original = self.record()
        forged = original.body()
        forged["cursor"] = "BIGWAVE_02/SPOOFED"
        decoded = c.parse_checkpoint(self.encode_raw(forged))
        self.assertEqual(decoded.cursor, "BIGWAVE_02/SPOOFED")
        self.assertFalse(c.plan_resume(decoded)["task_execution_performed"])
        # A valid digest is not a signature or an authorization to execute.
        self.assertEqual(c.plan_resume(decoded)["verdict"], "AWAIT_OPERATOR_APPROVAL")

    def test_pending_unknown_committed_never_replay_even_if_approved(self):
        for state in (c.SideEffect.PENDING, c.SideEffect.UNKNOWN, c.SideEffect.COMMITTED):
            with self.subTest(state=state):
                verdict = c.plan_resume(self.record(effect=state), operator_approved=True)
                self.assertEqual(verdict["verdict"], "BLOCKED_PENDING_REVIEW")
                self.assertFalse(verdict["external_effect_replayed"])

    def test_zero_effect_with_approval_is_only_manual_plan(self):
        verdict = c.plan_resume(self.record(), operator_approved=True)
        self.assertEqual(verdict["verdict"], "PLAN_READY_MANUAL_EXECUTION")
        self.assertFalse(verdict["task_execution_performed"])
        self.assertFalse(verdict["external_effect_replayed"])

    def test_nan_and_infinity_fail_closed_with_fixed_error(self):
        payload = self.record().body()
        encoded = c.serialize_checkpoint(self.record()).decode("ascii")
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                tampered = encoded.replace('"generation":0', f'"generation":{constant}')
                self.assertNotEqual(tampered, encoded)
                with self.assertRaises(c.ContinuityError) as exc:
                    c.parse_checkpoint(tampered.encode("ascii"))
                self.assertEqual(exc.exception.code, "CHECKPOINT_JSON_INVALID")

    def test_invalid_duplicate_json_fields(self):
        raw = c.serialize_checkpoint(self.record())
        doc = raw.decode("ascii")
        forged = doc.replace('"task_id":', '"task_id":"task-012345abcdef","task_id":')
        with self.assertRaises(c.ContinuityError) as exc:
            c.parse_checkpoint(forged.encode("ascii"))
        self.assertEqual(exc.exception.code, "CHECKPOINT_DUPLICATE_KEY")

    def test_nested_symlink_ancestor_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "outer" / "inner"
            root.mkdir(parents=True)
            parent = root.parent
            old_lstat = Path.lstat
            def fake_lstat(path):
                meta = old_lstat(path)
                if path == parent:
                    class Fake:
                        st_mode = meta.st_mode
                        st_file_attributes = 0x400
                    return Fake()
                return meta
            with patch.object(Path, "lstat", fake_lstat):
                with self.assertRaises(c.ContinuityError) as exc:
                    c.persist_checkpoint(root, self.record())
            self.assertEqual(exc.exception.code, "CHECKPOINT_DIRECTORY_UNSAFE")
            self.assertFalse((root / "TASK_CHECKPOINT.json").exists())

    def test_stale_writer_lock_is_not_stolen_after_crash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".raif-continuity.lock").mkdir()
            with self.assertRaises(c.ContinuityError) as exc:
                c.persist_checkpoint(root, self.record())
            self.assertEqual(exc.exception.code, "CHECKPOINT_WRITER_BUSY")
            self.assertTrue((root / ".raif-continuity.lock").is_dir())
            self.assertFalse((root / "TASK_CHECKPOINT.json").exists())

    def test_directory_lock_suppresses_interleaved_generation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            c.persist_checkpoint(root, self.record(1))
            with self.assertRaises(c.ContinuityError) as exc:
                c.persist_checkpoint(root, self.record(1))
            self.assertEqual(exc.exception.code, "CHECKPOINT_GENERATION_NOT_MONOTONIC")
            self.assertEqual(c.load_checkpoint(root).generation, 1)

    def test_corrupt_checkpoint_cannot_be_overwritten_unnoticed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            c.persist_checkpoint(root, self.record(2))
            (root / "TASK_CHECKPOINT.json").write_bytes(b"NOT_JSON")
            with self.assertRaises(c.ContinuityError) as exc:
                c.persist_checkpoint(root, self.record(3))
            self.assertEqual(exc.exception.code, "CHECKPOINT_JSON_INVALID")
            self.assertEqual((root / "TASK_CHECKPOINT.json").read_bytes(), b"NOT_JSON")

    def test_effect_state_downgrade_and_cross_transition_blocked(self):
        # A later generation must not erase PENDING/UNKNOWN/COMMITTED evidence.
        for earlier in (c.SideEffect.PENDING, c.SideEffect.UNKNOWN, c.SideEffect.COMMITTED):
            for later in c.SideEffect:
                if later is earlier:
                    continue
                with self.subTest(earlier=earlier, later=later), tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    first = self.record(0, earlier)
                    c.persist_checkpoint(root, first)
                    before = (root / "TASK_CHECKPOINT.json").read_bytes()
                    with self.assertRaises(c.ContinuityError) as exc:
                        c.persist_checkpoint(root, self.record(1, later))
                    self.assertEqual(exc.exception.code, "CHECKPOINT_EFFECT_TRANSITION_REQUIRES_REVIEW")
                    self.assertEqual((root / "TASK_CHECKPOINT.json").read_bytes(), before)
                    after = c.load_checkpoint(root)
                    self.assertEqual(after, first)
                    self.assertEqual(c.plan_resume(after, operator_approved=True)["verdict"],
                                     "BLOCKED_PENDING_REVIEW")

    def test_same_effect_higher_generation_still_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            c.persist_checkpoint(root, self.record(0, c.SideEffect.UNKNOWN))
            second = self.record(1, c.SideEffect.UNKNOWN)
            c.persist_checkpoint(root, second)
            self.assertEqual(c.load_checkpoint(root), second)

    def test_lineage_replaced_by_new_task_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            c.persist_checkpoint(root, self.record(0))
            foreign = c.ContinuityRecord("task-aaaaaaaaaaaa", "a" * 40,
                                         "BIGWAVE_02/RECOVERY", 1, c.SideEffect.NONE)
            with self.assertRaises(c.ContinuityError) as exc:
                c.persist_checkpoint(root, foreign)
            self.assertEqual(exc.exception.code, "CHECKPOINT_LINEAGE_MISMATCH")

    def test_windows_toctou_handle_lock_and_directory_flush(self):
        """Verify Windows handle lock prevents concurrent rename and executes metadata flush."""
        if sys.platform != "win32":
            return
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "target_dir"
            root.mkdir()
            renamed = Path(d) / "renamed_dir"

            # Hook serialize_checkpoint to attempt renaming directory while handle lock is held
            orig_serialize = c.serialize_checkpoint
            rename_failed = []

            def _concurrent_rename_hook(record):
                try:
                    root.rename(renamed)
                except OSError as e:
                    rename_failed.append(type(e).__name__)
                return orig_serialize(record)

            with patch.object(c, "serialize_checkpoint", side_effect=_concurrent_rename_hook):
                c.persist_checkpoint(root, self.record(0))

            # Concurrency check: rename must have been blocked while persist_checkpoint was active
            self.assertTrue(len(rename_failed) == 1, "Concurrent rename must be blocked by Windows handle")
            self.assertEqual(rename_failed[0], "PermissionError")
            self.assertTrue(root.exists(), "Original directory must still exist")
            self.assertFalse(renamed.exists(), "Renamed directory must not exist")

            # Checkpoint file exists and is valid
            self.assertEqual(c.load_checkpoint(root), self.record(0))

            # After persist_checkpoint completes, handle is released and rename succeeds
            root.rename(renamed)
            self.assertTrue(renamed.exists(), "Directory can be renamed once write finishes")


if __name__ == "__main__":
    unittest.main()

