"""W2/10.5: foreground cancellation, fencing, owner-only Windows Job, no replay."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rai_fabric.effect_ledger import EffectLedger, SyntheticSQLiteTarget
from rai_fabric.foreground_w2 import recover_foreground_synthetic, run_foreground_synthetic_once
from rai_fabric.store import FabricError, FabricStore
from rai_fabric.windows_owned_job import run_synthetic_job

DIGEST = hashlib.sha256(b"w2-10-5-synthetic-fixture").hexdigest()
EXIT_OK = {"verdict": "EXITED", "exit_code": 0, "owned_job": True,
           "descendants_active": 0, "external_provider_calls": 0}
EXIT_BAD = {"verdict": "EXITED", "exit_code": 7, "owned_job": True,
            "descendants_active": 0, "external_provider_calls": 0}
TIMEOUT = {"verdict": "OWNED_GROUP_TERMINATED", "owned_job": True,
           "descendants_active": 0, "external_provider_calls": 0}


class ForegroundOfflineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="raif-w2-fg-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store_path = self.root / "store.sqlite3"
        self.target_path = self.root / "target.sqlite3"
        self.store = FabricStore(self.store_path, initialize=True)
        self.addCleanup(self.store.close)
        self.ledger = EffectLedger.install_on_empty_store(self.store)
        self.target = SyntheticSQLiteTarget(self.target_path, "fixture-target", initialize=True)
        self.addCleanup(self.target.close)

    def submit(self, *, provider="mock", task_id="fixture-task"):
        return self.store.submit("Only synthetic fixture", provider, str(self.root),
                                 task_id=task_id)

    def run_fake(self, result=EXIT_OK, *, op="operation-1"):
        with (patch("rai_fabric.foreground_w2.sys.platform", "win32"),
              patch("rai_fabric.foreground_w2.run_synthetic_job", return_value=result)) as invoked:
            answer = run_foreground_synthetic_once(self.store, self.target,
                       operation_id=op, payload_sha256=DIGEST, task_id="fixture-task")
        return answer, invoked

    def test_success_has_independent_receipt_and_no_replay(self):
        self.submit()
        result, job = self.run_fake()
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["effect_phase"], "APPLIED_VERIFIED")
        self.assertEqual(result["receipt_count"], 1)
        self.assertEqual(result["external_provider_calls"], 0)
        self.assertEqual(self.target.readback("operation-1")["revision"], 1)
        self.assertEqual(self.store.get("fixture-task")["attempt"], 1)
        self.assertEqual(job.call_count, 1)
        self.assertTrue(callable(job.call_args.kwargs["cancel_check"]))
        with self.assertRaises(FabricError):
            self.store.requeue("fixture-task", acknowledgement="explicit checked outcome")
        self.assertNotIn("lease_token", json.dumps(result))

    def test_timeout_is_blocked_unknown_and_never_requeued(self):
        self.submit()
        answer, _ = self.run_fake(TIMEOUT)
        self.assertEqual((answer["status"], answer["effect_phase"]),
                         ("BLOCKED", "UNKNOWN_OUTCOME"))
        self.assertIsNone(self.target.readback("operation-1"))
        with self.assertRaises(FabricError):
            self.store.requeue("fixture-task", acknowledgement="operator confirmed no effect")
        self.assertEqual(self.store.get("fixture-task")["attempt"], 1)

    def test_nonzero_is_not_success(self):
        self.submit()
        answer, _ = self.run_fake(EXIT_BAD)
        self.assertEqual(answer["status"], "BLOCKED")
        self.assertEqual(answer["receipt_count"], 0)

    def test_job_evidence_lie_fails_closed(self):
        self.submit()
        bogus = dict(EXIT_OK, descendants_active=3)
        answer, _ = self.run_fake(bogus)
        self.assertEqual(answer["status"], "BLOCKED")
        self.assertEqual(answer["effect_phase"], "UNKNOWN_OUTCOME")

    def test_failing_target_does_not_claim_applied(self):
        self.submit()
        with patch.object(self.target, "apply", side_effect=RuntimeError("private failure text")):
            answer, _ = self.run_fake()
        self.assertEqual(answer["status"], "BLOCKED")
        self.assertEqual(answer["effect_phase"], "UNKNOWN_OUTCOME")
        self.assertNotIn("private failure text", json.dumps(answer))

    def test_lost_ack_after_target_commit_requires_readback(self):
        self.submit()
        original = self.target.apply
        def commit_then_crash(*args):
            original(*args)
            raise RuntimeError("after target commit before ack")
        with patch.object(self.target, "apply", side_effect=commit_then_crash):
            answer, _ = self.run_fake()
        self.assertEqual(answer["status"], "BLOCKED")
        self.assertEqual(answer["effect_phase"], "UNKNOWN_OUTCOME")
        self.assertEqual(self.target.readback("operation-1")["revision"], 1)
        self.assertEqual(self.ledger.reconcile_synthetic(self.target, "operation-1")["phase"],
                         "APPLIED_VERIFIED")
        with self.assertRaises(FabricError):
            self.store.requeue("fixture-task", acknowledgement="no duplicate authorized")

    def test_explicit_cancel_terminates_before_target(self):
        self.submit()
        def injected_job(*args, **kwargs):
            self.store.request_cancel("fixture-task")
            self.assertTrue(kwargs["cancel_check"]())
            return {"verdict": "OWNED_GROUP_CANCELLED"}
        with (patch("rai_fabric.foreground_w2.sys.platform", "win32"),
              patch("rai_fabric.foreground_w2.run_synthetic_job", side_effect=injected_job)):
            result = run_foreground_synthetic_once(self.store, self.target,
                     operation_id="operation-1", payload_sha256=DIGEST,
                     task_id="fixture-task")
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(result["effect_phase"], "UNKNOWN_OUTCOME")
        self.assertIsNone(self.target.readback("operation-1"))
        self.assertEqual(self.store.get("fixture-task")["attempt"], 1)

    def test_invalid_case_fails_before_claim(self):
        self.submit()
        with patch("rai_fabric.foreground_w2.sys.platform", "win32"):
            with self.assertRaises(FabricError):
                run_foreground_synthetic_once(self.store, self.target,
                    operation_id="operation-1", payload_sha256=DIGEST,
                    case="python.exe", task_id="fixture-task")
        self.assertEqual(self.store.get("fixture-task")["attempt"], 0)

    def test_bad_payload_fails_before_claim(self):
        self.submit()
        with patch("rai_fabric.foreground_w2.sys.platform", "win32"):
            with self.assertRaises(FabricError):
                run_foreground_synthetic_once(self.store, self.target,
                    operation_id="operation-1", payload_sha256="raw secret",
                    task_id="fixture-task")
        self.assertEqual(self.store.get("fixture-task")["attempt"], 0)

    def test_real_provider_does_not_gain_execution(self):
        self.submit(provider="antigravity")
        with patch("rai_fabric.foreground_w2.sys.platform", "win32"):
            result = run_foreground_synthetic_once(self.store, self.target,
                      operation_id="operation-1", payload_sha256=DIGEST,
                      task_id="fixture-task")
        self.assertEqual(result["status"], "NO_READY_TASK")
        self.assertEqual(self.store.get("fixture-task")["attempt"], 0)

    def test_foreground_refuses_uninitialized_schema(self):
        with FabricStore(self.root / "legacy.db", initialize=True) as older:
            older.submit("legacy", "mock", str(self.root), task_id="legacy")
            with patch("rai_fabric.foreground_w2.sys.platform", "win32"):
                with self.assertRaises(FabricError):
                    run_foreground_synthetic_once(older, self.target,
                        operation_id="operation-1", payload_sha256=DIGEST, task_id="legacy")
            self.assertEqual(older.get("legacy")["attempt"], 0)

    def test_no_work_in_queue_does_not_mutate_sqlite(self):
        with patch("rai_fabric.foreground_w2.sys.platform", "win32"):
            result = run_foreground_synthetic_once(self.store, self.target,
                     operation_id="operation-1", payload_sha256=DIGEST)
        self.assertEqual(result["status"], "NO_READY_TASK")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)

    def test_recovery_is_readback_only_no_replay(self):
        self.submit()
        c = self.store.claim("dead-worker", task_id="fixture-task")
        self.ledger.prepare_effect("fixture-task", "dead-worker", c["lease_token"],
            target_id="fixture-target", operation_id="operation-1",
            payload_sha256=DIGEST, expected_revision="rev-0")
        self.ledger.mark_possible_dispatch("fixture-task", "dead-worker", c["lease_token"],
            target_id="fixture-target", operation_id="operation-1")
        self.store.db.execute("UPDATE tasks SET lease_deadline=? WHERE id=?",
                              (time.time() - 3, "fixture-task"))
        result = recover_foreground_synthetic(self.store)
        self.assertEqual(result["blocked_task_ids"], ["fixture-task"])
        self.assertEqual(result["replayed"], 0)
        self.assertEqual(self.ledger.get("fixture-target", "operation-1")["phase"],
                         "UNKNOWN_OUTCOME")
        self.assertIsNone(self.store.claim("other-worker", provider="mock"))

    def test_nonwindows_refuses_before_claim(self):
        self.submit()
        if sys.platform != "win32":
            with self.assertRaises(FabricError):
                run_foreground_synthetic_once(self.store, self.target,
                    operation_id="operation-1", payload_sha256=DIGEST)
            self.assertEqual(self.store.get("fixture-task")["attempt"], 0)


@unittest.skipUnless(sys.platform == "win32", "Owned Windows Job integration")
class ForegroundWindowsJobTests(ForegroundOfflineTests):
    def test_actual_job_success_and_receipt(self):
        self.submit()
        result = run_foreground_synthetic_once(self.store, self.target,
                 operation_id="win-success", payload_sha256=DIGEST,
                 timeout_seconds=8, task_id="fixture-task")
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["effect_phase"], "APPLIED_VERIFIED")

    def test_actual_job_timeout_blocks_replay(self):
        self.submit()
        result = run_foreground_synthetic_once(self.store, self.target,
                 operation_id="win-timeout", payload_sha256=DIGEST,
                 case="HANG_PARENT", timeout_seconds=0.6, task_id="fixture-task")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["effect_phase"], "UNKNOWN_OUTCOME")

    def test_owned_job_cancellation_tree_is_reaped(self):
        seen = {"calls": 0}
        def cancel():
            seen["calls"] += 1
            return seen["calls"] >= 2
        result = run_synthetic_job("HANG_PARENT", timeout_seconds=5,
                                   cancel_check=cancel)
        self.assertEqual(result["verdict"], "OWNED_GROUP_CANCELLED")
        self.assertEqual(result["descendants_active"], 0)
        self.assertGreaterEqual(seen["calls"], 2)

    def test_win_cancel_callback_invalid_rejected(self):
        with self.assertRaises(FabricError):
            run_synthetic_job("EXIT_ZERO", cancel_check=object())

    def test_real_external_cancel_request_does_not_replay(self):
        self.submit()
        def execute():
            with FabricStore(self.store_path) as second:
                with SyntheticSQLiteTarget(self.target_path, "fixture-target") as sink:
                    return run_foreground_synthetic_once(second, sink,
                        operation_id="win-cancel", payload_sha256=DIGEST,
                        case="HANG_PARENT", timeout_seconds=8,
                        task_id="fixture-task")
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                row = self.store.db.execute("SELECT phase FROM effect_operations WHERE operation_id=?",
                                            ("win-cancel",)).fetchone()
                if row is not None and row[0] == "MAY_HAVE_RUN":
                    break
                time.sleep(.03)
            else:
                self.fail("foreground did not enter MAY_HAVE_RUN")
            self.store.request_cancel("fixture-task")
            result = future.result(timeout=10)
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(result["effect_phase"], "UNKNOWN_OUTCOME")
        self.assertIsNone(self.target.readback("win-cancel"))


if __name__ == "__main__":
    unittest.main()
