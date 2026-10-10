"""CP-54D checkpoint, corruption and idempotency synthetic tests."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raif_ag_supervisor.continuity import (
    ContinuityError, ContinuityRecord, SideEffect,
    serialize_checkpoint, parse_checkpoint, plan_resume,
    persist_checkpoint, load_checkpoint,
)


def sample(effect=SideEffect.NONE):
    return ContinuityRecord("task-012345abcdef", "1"*40,
                            "RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE", 2, effect)


class ContinuityTests(unittest.TestCase):
    def test_valid_roundtrip(self):
        record=sample()
        self.assertEqual(parse_checkpoint(serialize_checkpoint(record)), record)

    def test_sha_tampering_blocked(self):
        raw=serialize_checkpoint(sample()).replace(b'"generation":2',b'"generation":3')
        with self.assertRaises(ContinuityError) as cm:
            parse_checkpoint(raw)
        self.assertEqual(cm.exception.code, "CHECKPOINT_HASH_MISMATCH")

    def test_duplicate_keys_rejected(self):
        raw=serialize_checkpoint(sample())
        tampered=raw.replace(b'"payload":',b'"payload":null,"payload":')
        with self.assertRaises(ContinuityError) as cm:
            parse_checkpoint(tampered)
        self.assertEqual(cm.exception.code, "CHECKPOINT_DUPLICATE_KEY")

    def test_invalid_cursor_and_sensitive_string_rejected(self):
        for cursor in ("C:/USER/secret@example.test", "../../ESCAPE", "RAIF\nTOKEN", ""): 
            with self.subTest(cursor=cursor), self.assertRaises(ContinuityError):
                ContinuityRecord("task-012345abcdef", "1"*40,cursor,1,SideEffect.NONE)

    def test_invalid_id_sha_generation_and_effect(self):
        valid=sample()
        for updates in ({"task_id":"person@example.test"}, {"git_sha":"bad"},
                        {"generation":True}, {"generation":-1},
                        {"effect":"NONE"}):
            kw=dict(task_id=valid.task_id,git_sha=valid.git_sha,cursor=valid.cursor,
                    generation=valid.generation,effect=valid.effect)
            kw.update(updates)
            with self.subTest(updates=updates),self.assertRaises(ContinuityError):
                ContinuityRecord(**kw)

    def test_unknown_effect_never_replays(self):
        for effect in (SideEffect.UNKNOWN,SideEffect.COMMITTED,SideEffect.PENDING):
            with self.subTest(effect=effect):
                r=plan_resume(sample(effect),operator_approved=True)
                self.assertEqual(r["verdict"], "BLOCKED_PENDING_REVIEW")
                self.assertFalse(r["external_effect_replayed"])
                self.assertFalse(r["task_execution_performed"])

    def test_none_effect_requires_operator(self):
        record=sample()
        self.assertEqual(plan_resume(record)["verdict"], "AWAIT_OPERATOR_APPROVAL")
        r=plan_resume(record,operator_approved=True)
        self.assertEqual(r["verdict"], "PLAN_READY_MANUAL_EXECUTION")
        self.assertFalse(r["task_execution_performed"])

    def test_persist_load_same_data(self):
        with tempfile.TemporaryDirectory() as path:
            persist_checkpoint(Path(path),sample(SideEffect.PENDING))
            self.assertEqual(load_checkpoint(Path(path)),sample(SideEffect.PENDING))

    def test_stale_generation_and_lineage_are_blocked(self):
        with tempfile.TemporaryDirectory() as path:
            root=Path(path)
            persist_checkpoint(root,sample())
            with self.assertRaises(ContinuityError) as cm:
                persist_checkpoint(root,sample())
            self.assertEqual(cm.exception.code,"CHECKPOINT_GENERATION_NOT_MONOTONIC")
            with self.assertRaises(ContinuityError) as cm:
                persist_checkpoint(root,ContinuityRecord("task-aabbccddeeff","1"*40,
                    sample().cursor,3,SideEffect.UNKNOWN))
            self.assertEqual(cm.exception.code,"CHECKPOINT_LINEAGE_MISMATCH")
            self.assertEqual(load_checkpoint(root),sample())

    def test_crash_lock_never_auto_stolen(self):
        with tempfile.TemporaryDirectory() as path:
            root=Path(path)
            (root/".raif-continuity.lock").mkdir()
            with self.assertRaises(ContinuityError) as cm:
                persist_checkpoint(root,sample())
            self.assertEqual(cm.exception.code,"CHECKPOINT_WRITER_BUSY")
            self.assertTrue((root/".raif-continuity.lock").is_dir())

    def test_next_generation_allowed(self):
        with tempfile.TemporaryDirectory() as path:
            root=Path(path)
            persist_checkpoint(root,sample())
            next_record=ContinuityRecord(sample().task_id,sample().git_sha,
               sample().cursor,3,SideEffect.UNKNOWN)
            persist_checkpoint(root,next_record)
            self.assertEqual(load_checkpoint(root),next_record)

    def test_corrupted_file_does_not_get_accepted(self):
        with tempfile.TemporaryDirectory() as path:
            root=Path(path)
            persist_checkpoint(root,sample())
            (root/"TASK_CHECKPOINT.json").write_text("{evil}",encoding="utf-8")
            with self.assertRaises(ContinuityError):
                load_checkpoint(root)

    def test_write_failure_preserves_old_checkpoint(self):
        with tempfile.TemporaryDirectory() as path:
            root=Path(path)
            persist_checkpoint(root,sample())
            with patch("raif_ag_supervisor.continuity.os.replace",side_effect=OSError("private-path")):
                with self.assertRaises(ContinuityError) as cm:
                    persist_checkpoint(root,ContinuityRecord("task-012345abcdef","1"*40,
                        sample().cursor,3,SideEffect.UNKNOWN))
            self.assertEqual(cm.exception.code,"CHECKPOINT_WRITE_FAILED")
            self.assertEqual(load_checkpoint(root),sample())
            self.assertFalse(any(p.suffix==".tmp" for p in root.iterdir()))

    def test_directory_missing_fails_closed(self):
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaises(ContinuityError):
                persist_checkpoint(Path(path)/"nonexistent",sample())

    def test_missing_checkpoint_safe_code(self):
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaises(ContinuityError) as cm:
                load_checkpoint(Path(path))
            self.assertEqual(cm.exception.code, "CHECKPOINT_READ_FAILED")

    def test_symlink_blocked_if_possible(self):
        with tempfile.TemporaryDirectory() as path:
            root=Path(path)
            target=root/"other.json"
            target.write_text("private",encoding="utf-8")
            link=root/"TASK_CHECKPOINT.json"
            try:
                link.symlink_to(target)
            except (OSError,NotImplementedError):
                self.skipTest("Windows symlink privileges unavailable")
            with self.assertRaises(ContinuityError):
                persist_checkpoint(root,sample())
            with self.assertRaises(ContinuityError):
                load_checkpoint(root)
            self.assertEqual(target.read_text(encoding="utf-8"), "private")

    def test_size_cap(self):
        with self.assertRaises(ContinuityError) as cm:
            parse_checkpoint(b"X"*5000)
        self.assertEqual(cm.exception.code,"CHECKPOINT_SIZE_INVALID")


if __name__ == "__main__":
    unittest.main()
