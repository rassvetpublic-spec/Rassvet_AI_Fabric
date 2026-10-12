"""W2: потерянный ACK, fencing, receipt, 2 SQLite-файла и 2 соединения.

Все эффекты синтетические; внешние провайдеры и пользовательская БД не используются.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rai_fabric.store import FabricError, FabricStore
from rai_fabric.effect_ledger import EffectLedger, SyntheticSQLiteTarget

DIGEST = hashlib.sha256(b"synthetic-payload-1").hexdigest()
OTHER = hashlib.sha256(b"synthetic-payload-2").hexdigest()


class W2EffectLedgerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="raif-w2-effect-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / "fabric.db"
        self.store = FabricStore(self.path, initialize=True)
        self.addCleanup(self.store.close)
        self.ledger = EffectLedger.install_on_empty_store(self.store)
        self.sink_path = self.root / "independent-sink.db"
        self.sink = SyntheticSQLiteTarget(self.sink_path, "local-sink", initialize=True)
        self.addCleanup(self.sink.close)
        self.store.submit("Проверка W2 offline", "mock", str(self.root), task_id="task-w2")
        self.claim = self.store.claim("worker-1", task_id="task-w2")

    def prepare(self, name="op-1", digest=DIGEST):
        return self.ledger.prepare_effect(
            "task-w2", "worker-1", self.claim["lease_token"],
            target_id="local-sink", operation_id=name,
            payload_sha256=digest, expected_revision="rev-0",
        )

    def dispatch(self, name="op-1"):
        return self.ledger.mark_possible_dispatch(
            "task-w2", "worker-1", self.claim["lease_token"],
            target_id="local-sink", operation_id=name,
        )

    def expire(self):
        self.store.db.execute(
            "UPDATE tasks SET lease_deadline=? WHERE id=?", (time.time() - 2, "task-w2")
        )
        self.assertEqual(self.store.recover(), ["task-w2"])

    def test_schema_version_is_opt_in_and_persists(self):
        self.assertEqual(self.store.db.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0], "2")
        with FabricStore(self.path) as reopened:
            EffectLedger(reopened)
            self.assertEqual(reopened.get("task-w2")["status"], "RUNNING")

    def test_cannot_install_on_nonempty_legacy_database(self):
        with FabricStore(self.root / "legacy.db", initialize=True) as old:
            old.submit("Текущая задача", "mock", str(self.root), task_id="old")
            with self.assertRaises(FabricError):
                EffectLedger.install_on_empty_store(old)
            self.assertEqual(old.db.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()[0], "1")
            self.assertFalse(old.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='effect_operations'"
            ).fetchone())

    def test_cannot_install_twice_or_create_ledgers_implicitly(self):
        with self.assertRaises(FabricError):
            EffectLedger.install_on_empty_store(self.store)
        with FabricStore(self.root / "other.db", initialize=True) as fresh:
            with self.assertRaises(FabricError):
                EffectLedger(fresh)

    def test_unauthorized_token_cannot_prepare_or_dispatch(self):
        with self.assertRaises(FabricError):
            self.ledger.prepare_effect(
                "task-w2", "worker-1", "WRONG", target_id="local-sink",
                operation_id="op-1", payload_sha256=DIGEST,
                expected_revision="rev-0",
            )
        self.prepare()
        with self.assertRaises(FabricError):
            self.ledger.mark_possible_dispatch(
                "task-w2", "other-worker", self.claim["lease_token"],
                target_id="local-sink", operation_id="op-1",
            )
        self.assertEqual(self.ledger.get("local-sink", "op-1")["phase"], "PREPARED")

    def test_same_operation_intent_is_idempotent_but_conflicts_block(self):
        self.prepare()
        self.assertEqual(self.prepare()["phase"], "PREPARED")
        with self.assertRaises(FabricError):
            self.prepare(digest=OTHER)
        with self.assertRaises(FabricError):
            self.ledger.prepare_effect(
                "task-w2", "worker-1", self.claim["lease_token"],
                target_id="local-sink", operation_id="op-1",
                payload_sha256=DIGEST, expected_revision="rev-999",
            )
        self.assertEqual(len(self.ledger.list_for_task("task-w2")), 1)

    def test_same_payload_different_operations_are_not_duplicates(self):
        self.prepare("op-1")
        self.prepare("op-2")
        self.assertEqual(len(self.ledger.list_for_task("task-w2")), 2)

    def test_different_task_same_operation_is_rejected(self):
        self.prepare()
        self.store.submit("Другая задача", "mock", str(self.root), task_id="other")
        second = self.store.claim("worker-2", task_id="other")
        with self.assertRaises(FabricError):
            self.ledger.prepare_effect(
                "other", "worker-2", second["lease_token"],
                target_id="local-sink", operation_id="op-1",
                payload_sha256=DIGEST, expected_revision="rev-0",
            )

    def test_dispatch_mark_is_one_shot(self):
        self.prepare()
        self.assertEqual(self.dispatch()["phase"], "MAY_HAVE_RUN")
        with self.assertRaises(FabricError):
            self.dispatch()
        self.assertEqual(self.ledger.get("local-sink", "op-1")["phase"], "MAY_HAVE_RUN")

    def test_prepared_without_dispatch_can_verify_no_effect_not_pass(self):
        self.prepare()
        result = self.ledger.reconcile_synthetic(self.sink, "op-1")
        self.assertEqual(result["phase"], "NO_EFFECT_VERIFIED")
        with self.assertRaises(FabricError):
            self.store.finish("task-w2", "worker-1", self.claim["lease_token"],
                              verdict="PASS", response="no effect", evidence={})
        self.store.finish("task-w2", "worker-1", self.claim["lease_token"],
                          verdict="BLOCKED", response="not executed", evidence={})
        with self.assertRaises(FabricError):
            self.store.requeue("task-w2", acknowledgement="подтверждение отсутствия")
        self.assertEqual(len(self.ledger.receipts_for_task("task-w2")), 1)

    def test_lost_ack_marks_unknown_and_never_requeues(self):
        self.prepare()
        self.dispatch()
        self.sink.apply("op-1", DIGEST)
        # Crash occurs AFTER target commit, BEFORE Fabric ACK.
        self.expire()
        self.assertEqual(self.ledger.get("local-sink", "op-1")["phase"], "UNKNOWN_OUTCOME")
        self.assertEqual(self.store.get("task-w2")["status"], "BLOCKED")
        self.assertEqual(self.ledger.recover_pending_effects(), [])
        with self.assertRaises(FabricError):
            self.store.requeue("task-w2", acknowledgement="reconciled-and-confirmed")
        self.assertIsNone(self.store.claim("fresh-worker"))
        result = self.ledger.reconcile_synthetic(self.sink, "op-1")
        self.assertEqual(result["phase"], "APPLIED_VERIFIED")
        self.assertEqual(self.sink.readback("op-1")["revision"], 1)
        receipts = self.ledger.receipts_for_task("task-w2")
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["readback_class"], "SYNTHETIC_SQLITE_TARGET_READBACK")
        with self.assertRaises(FabricError):
            self.store.requeue("task-w2", acknowledgement="confirmed-applied-effect")

    def test_missing_target_receipt_after_possible_dispatch_stays_blocked(self):
        self.prepare()
        self.dispatch()
        self.expire()
        self.assertEqual(
            self.ledger.reconcile_synthetic(self.sink, "op-1")["phase"], "BLOCKED_RECONCILE"
        )
        self.assertEqual(self.ledger.receipts_for_task("task-w2"), [])
        self.assertEqual(self.ledger.recover_pending_effects(), [])

    def test_payload_mismatch_cannot_launder_applied_receipt(self):
        self.prepare()
        self.dispatch()
        self.sink.apply("op-1", OTHER)
        self.expire()
        self.assertEqual(
            self.ledger.reconcile_synthetic(self.sink, "op-1")["phase"], "BLOCKED_RECONCILE"
        )
        self.assertEqual(self.ledger.receipts_for_task("task-w2"), [])

    def test_synthetic_target_rejects_same_id_different_payload(self):
        self.sink.apply("op-1", DIGEST)
        with self.assertRaises(FabricError):
            self.sink.apply("op-1", OTHER)
        self.assertEqual(self.sink.readback("op-1")["payload_sha256"], DIGEST)

    def test_expired_lease_cannot_prepare_or_dispatch(self):
        self.prepare()
        self.store.db.execute(
            "UPDATE tasks SET lease_deadline=? WHERE id=?", (time.time() - 1, "task-w2")
        )
        with self.assertRaises(FabricError):
            self.dispatch()
        with self.assertRaises(FabricError):
            self.prepare(name="op-2")

    def test_prepared_crash_cannot_auto_requeue(self):
        self.prepare()
        self.expire()
        self.assertEqual(self.ledger.get("local-sink", "op-1")["phase"], "PREPARED")
        with self.assertRaises(FabricError):
            self.store.requeue("task-w2", acknowledgement="checked and verified")
        self.assertEqual(self.store.get("task-w2")["status"], "BLOCKED")

    def test_pass_for_unverified_external_effect_is_blocked(self):
        self.prepare()
        self.dispatch()
        with self.assertRaises(FabricError):
            self.store.finish("task-w2", "worker-1", self.claim["lease_token"],
                              verdict="PASS", response="unverified", evidence={})
        self.assertEqual(self.store.get("task-w2")["status"], "RUNNING")

    def test_two_sqlite_connections_compete_for_one_dispatch(self):
        self.prepare()
        def try_dispatch(_):
            with FabricStore(self.path) as other:
                ledger = EffectLedger(other)
                try:
                    return ledger.mark_possible_dispatch(
                        "task-w2", "worker-1", self.claim["lease_token"],
                        target_id="local-sink", operation_id="op-1",
                    )["phase"]
                except FabricError:
                    return "DENIED"
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(try_dispatch, range(2)))
        self.assertEqual(sorted(results), ["DENIED", "MAY_HAVE_RUN"])

    def test_receipt_immutable_and_durable_after_reopen(self):
        self.prepare()
        self.dispatch()
        self.sink.apply("op-1", DIGEST)
        self.ledger.reconcile_synthetic(self.sink, "op-1")
        with FabricStore(self.path) as reopened:
            ledger = EffectLedger(reopened)
            self.assertEqual(ledger.get("local-sink", "op-1")["phase"], "APPLIED_VERIFIED")
            r = ledger.receipts_for_task("task-w2")
            self.assertEqual(len(r), 1)
            self.assertRegex(r[0]["evidence_sha256"], "^[0-9a-f]{64}$")
            with self.assertRaises(sqlite3.DatabaseError):
                reopened.db.execute("DELETE FROM effect_receipts")

    def test_log_records_only_digest_no_raw_payload(self):
        self.prepare()
        self.dispatch()
        data = json.dumps(self.ledger.list_for_task("task-w2"))
        self.assertIn(DIGEST, data)
        self.assertNotIn("synthetic-payload-1", data)
        with self.assertRaises(FabricError):
            self.ledger.prepare_effect(
                "task-w2", "worker-1", self.claim["lease_token"],
                target_id="local-sink", operation_id="op-evil",
                payload_sha256="private raw prompt", expected_revision="rev-0",
            )


    def test_w2_external_worker_blocked_before_claim(self):
        from rai_fabric.worker import run_one
        self.store.submit("Synthetic external forbidden", "antigravity",
                          str(self.root), task_id="task-external")
        with self.assertRaises(FabricError) as cm:
            run_one(self.store, "antigravity", allow_external=True)
        self.assertIn("verified effect adapter", str(cm.exception))
        self.assertEqual(self.store.get("task-external")["status"], "QUEUED")
        self.assertEqual(self.store.get("task-external")["attempt"], 0)

    def test_w2_mock_remains_usable_without_new_provider_calls(self):
        from rai_fabric.worker import run_one
        self.store.submit("Synthetic mock safe", "mock",
                          str(self.root), task_id="task-mock-2")
        result = run_one(self.store, "mock")
        self.assertEqual(result["status"], "COMPLETE")
        self.assertTrue(result["checkpoint"]["evidence"]["simulation"])

    def test_untrusted_expected_revision_does_not_become_verified(self):
        self.ledger.prepare_effect(
            "task-w2", "worker-1", self.claim["lease_token"],
            target_id="local-sink", operation_id="op-revision",
            payload_sha256=DIGEST, expected_revision="rev-99",
        )
        self.dispatch("op-revision")
        self.sink.apply("op-revision", DIGEST)
        result = self.ledger.reconcile_synthetic(self.sink, "op-revision")
        self.assertEqual(result["phase"], "BLOCKED_RECONCILE")
        self.assertEqual(self.ledger.receipts_for_task("task-w2"), [])

    def test_direct_claim_is_not_an_external_W2_worker_bypass(self):
        self.store.submit("Real executor must remain disabled", "antigravity",
                          str(self.root), task_id="external-only")
        with self.assertRaises(FabricError):
            self.store.claim("manual", provider="antigravity", task_id="external-only")
        self.assertIsNone(self.store.claim("manual", task_id="external-only"))
        self.assertEqual(self.store.get("external-only")["status"], "QUEUED")
        self.assertEqual(self.store.get("external-only")["attempt"], 0)

    def test_direct_synthetic_effect_api_rejects_real_provider(self):
        self.store.submit("Deliberately malformed lease sandbox", "antigravity",
                          str(self.root), task_id="external-effect")
        token = "fixture-only-lease-token"
        # Fault injection only: simulate a W2 task row written by an older
        # implementation, bypassing the normal claim() contract.
        self.store.db.execute(
            "UPDATE tasks SET status='RUNNING',lease_owner=?,lease_hash=?,"
            "lease_epoch=1,lease_deadline=? WHERE id=?",
            ("synthetic-admin", hashlib.sha256(token.encode()).hexdigest(),
             time.time() + 60, "external-effect"),
        )
        with self.assertRaises(FabricError):
            self.ledger.prepare_effect(
                "external-effect", "synthetic-admin", token,
                target_id="local-sink", operation_id="external-op",
                payload_sha256=DIGEST, expected_revision="rev-0",
            )
        with self.assertRaises(FabricError):
            self.store.finish(
                "external-effect", "synthetic-admin", token, verdict="PASS",
                response="fake success", evidence={"simulation": True},
            )
        self.assertEqual(self.store.get("external-effect")["status"], "RUNNING")
        self.assertEqual(self.ledger.list_for_task("external-effect"), [])

    def test_applied_phase_without_receipt_does_not_pass(self):
        self.prepare()
        self.dispatch()
        # Simulate partial DB corruption or a faulty writer: the phase alone
        # is not independent target evidence and must not authorize COMPLETE.
        self.store.db.execute(
            "UPDATE effect_operations SET phase='APPLIED_VERIFIED' "
            "WHERE target_id='local-sink' AND operation_id='op-1'"
        )
        with self.assertRaises(FabricError):
            self.store.finish(
                "task-w2", "worker-1", self.claim["lease_token"],
                verdict="PASS", response="phase only", evidence={},
            )
        self.assertEqual(self.store.get("task-w2")["status"], "RUNNING")
        self.assertEqual(self.ledger.receipts_for_task("task-w2"), [])

    def test_corrupted_receipt_checksum_cannot_finish(self):
        self.prepare()
        self.dispatch()
        self.sink.apply("op-1", DIGEST)
        self.ledger.reconcile_synthetic(self.sink, "op-1")
        # Explicit fault injection in disposable DB. The immutable trigger
        # is removed only to model on-disk corruption, never in production.
        self.store.db.execute("DROP TRIGGER immutable_effect_receipt_update")
        self.store.db.execute(
            "UPDATE effect_receipts SET evidence_sha256=? WHERE operation_id='op-1'",
            ("0" * 64,),
        )
        with self.assertRaises(FabricError):
            self.store.finish(
                "task-w2", "worker-1", self.claim["lease_token"],
                verdict="PASS", response="checksum mismatch", evidence={},
            )
        self.assertEqual(self.store.get("task-w2")["status"], "RUNNING")

    def test_existing_sink_must_never_be_reinitialized(self):
        before = self.sink_path.stat().st_size
        with self.assertRaises(FabricError):
            SyntheticSQLiteTarget(self.sink_path, "local-sink", initialize=True)
        self.assertEqual(self.sink_path.stat().st_size, before)

    def test_verified_applied_can_finish_without_replay(self):
        self.prepare()
        self.dispatch()
        self.sink.apply("op-1", DIGEST)
        self.assertEqual(self.ledger.reconcile_synthetic(self.sink, "op-1")["phase"],
                         "APPLIED_VERIFIED")
        result = self.store.finish(
            "task-w2", "worker-1", self.claim["lease_token"],
            verdict="PASS", response="verified synthetic only",
            evidence={"simulation": True, "external_provider_calls": 0},
        )
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(len(self.ledger.receipts_for_task("task-w2")), 1)

    def test_invalid_target_directory_rejected_without_creating_file(self):
        destination = self.root / "blocked-target.db"
        with patch("rai_fabric.effect_ledger._safe_parent", return_value=False):
            with self.assertRaises(FabricError):
                SyntheticSQLiteTarget(destination, "local-sink", initialize=True)
        self.assertFalse(destination.exists())

    def test_separate_process_applies_after_dispatch_then_ack_lost(self):
        self.prepare()
        self.dispatch()
        self.sink.close()
        script = (
            "import sqlite3,sys;"
            "db=sqlite3.connect(sys.argv[1]);"
            "db.execute('INSERT INTO synthetic_effects "
            "(target_id,operation_id,payload_sha256,revision) VALUES(?,?,?,1)',"
            "('local-sink','op-1',sys.argv[2]));"
            "db.commit();db.close()"
        )
        proc = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script, str(self.sink_path), DIGEST],
            shell=False, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=8, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[:300])
        self.expire()
        with SyntheticSQLiteTarget(self.sink_path, "local-sink") as reopen_target:
            answer = self.ledger.reconcile_synthetic(reopen_target, "op-1")
        self.assertEqual(answer["phase"], "APPLIED_VERIFIED")


if __name__ == "__main__":
    unittest.main()
