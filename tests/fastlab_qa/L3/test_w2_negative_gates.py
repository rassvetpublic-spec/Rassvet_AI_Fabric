"""BPR5micro adversarial REPRO for FASTLAB L3 Block C source candidate.
All 6 negative tests must be GREEN against the hardened candidate source.
Only SQLite :memory: + TemporaryDirectory; no live provider/host/network.
"""
from __future__ import annotations
import hashlib
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

# Ensure rai_fabric is importable
import rai_fabric

from rai_fabric.store import FabricStore, FabricError

class FabricStoreMirror(FabricStore):
    def __init__(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          INSERT INTO meta VALUES ('schema_version','1');
          CREATE TABLE tasks(id TEXT PRIMARY KEY, objective TEXT, provider TEXT, workspace TEXT,
          status TEXT,lease_owner TEXT,lease_hash TEXT,lease_epoch INTEGER NOT NULL DEFAULT 0,
          lease_deadline REAL,attempt INTEGER NOT NULL DEFAULT 0,cancel_requested INTEGER NOT NULL DEFAULT 0,
          result_json TEXT,updated_at REAL);''')

    @contextmanager
    def atomic(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def submit(self, objective, provider, workspace, task_id):
        self.db.execute(
            'INSERT INTO tasks(id,objective,provider,workspace,status,updated_at) VALUES(?,?,?,?,?,?)',
            (task_id, objective, provider, workspace, 'QUEUED', time.time())
        )
        return {'id': task_id, 'status': 'QUEUED'}

    def _event(self, *args):
        pass

    def _checkpoint(self, *args):
        pass


from rai_fabric.w2_migration import migrate_store_v1_to_v2
from rai_fabric.w2_effect_bridge import register_real_intent, commit_verified_effect_receipt
from rai_fabric.effect_receipt_contract import EffectIntent, TargetEffectReceipt, ReceiptRejected
from rai_fabric.trusted_target_verifier import LocalTrustedGrantRegistry, LocalTargetReadbackVerifier

NOW = 1_800_000_100.0
CONTENT = b'a real-looking local file'
DIGEST = hashlib.sha256(CONTENT).hexdigest()


class CandidateGateRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='raif-w2-red-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'approved'
        self.root.mkdir()
        self.intent = EffectIntent(
            'test-task', 'antigravity', 'approved-target', 'RASSVET_DESKTOP',
            'file.txt', 'envelope-1', 1, NOW + 100, 'a' * 64, 'self-issued-grant'
        )
        self.receipt = TargetEffectReceipt(
            'test-task', 'antigravity', 'approved-target', 'RASSVET_DESKTOP',
            'file.txt', 'envelope-1', 1, 'APPLIED_VERIFIED', 'a' * 64, 'UNVERIFIED_REVISION',
            DIGEST, 'UNVERIFIED_ATTESTATION', NOW - 1
        )
        (self.root / 'file.txt').write_bytes(CONTENT)
        self.grant = LocalTrustedGrantRegistry()
        self.grant.register_grant(
            self.intent.owner_grant_ref, self.intent.task_id,
            self.intent.target_id, self.intent.lease_deadline_utc
        )
        self.verifier = LocalTargetReadbackVerifier()
        self.verifier.register_target_root(self.intent.target_id, self.root)

    def fresh_store(self):
        store = FabricStoreMirror()
        migrate_store_v1_to_v2(store)
        register_real_intent(store, self.intent, self.grant, workspace=self.root)
        self.addCleanup(store.db.close)
        return store

    def test_sibling_root_prefix_escape_must_be_denied(self):
        sibling = self.root.parent / 'approved_mimic'
        sibling.mkdir()
        (sibling / 'file.txt').write_bytes(CONTENT)
        sub = '..' + '/' + sibling.name + '/file.txt'
        intent = replace(self.intent, operation_id=sub)
        receipt = replace(self.receipt, operation_id=sub)
        self.assertIsNone(self.verifier.verify_target(intent, receipt))

    def test_unverified_target_revision_must_be_denied(self):
        self.assertIsNone(self.verifier.verify_target(self.intent, self.receipt))

    def test_unleased_queued_task_cannot_commit_real_pass(self):
        store = self.fresh_store()
        row = store.db.execute("SELECT status,lease_epoch,lease_owner FROM tasks").fetchone()
        self.assertEqual((row['status'], row['lease_epoch'], row['lease_owner']), ('QUEUED', 0, None))
        with self.assertRaises(ReceiptRejected):
            commit_verified_effect_receipt(
                store, self.intent, self.receipt, now_utc=NOW,
                grant_registry=self.grant, target_verifier=self.verifier
            )
        self.assertEqual(store.db.execute('SELECT status FROM tasks').fetchone()[0], 'QUEUED')

    def test_cancelled_task_cannot_reanimate_into_complete(self):
        store = self.fresh_store()
        store.db.execute("UPDATE tasks SET status='CANCELLED',cancel_requested=1")
        with self.assertRaises(ReceiptRejected):
            commit_verified_effect_receipt(
                store, self.intent, self.receipt, now_utc=NOW,
                grant_registry=self.grant, target_verifier=self.verifier
            )
        self.assertEqual(store.db.execute('SELECT status FROM tasks').fetchone()[0], 'CANCELLED')

    def test_mismatched_persisted_intent_must_be_denied(self):
        store = self.fresh_store()
        store.db.execute("UPDATE effect_intents SET payload_sha256=?", ('f' * 64,))
        with self.assertRaises(ReceiptRejected):
            commit_verified_effect_receipt(
                store, self.intent, self.receipt, now_utc=NOW,
                grant_registry=self.grant, target_verifier=self.verifier
            )

    def test_corrupt_v2_missing_immutable_trigger_must_not_be_accepted(self):
        store = FabricStoreMirror()
        self.addCleanup(store.db.close)
        migrate_store_v1_to_v2(store)
        store.db.execute("DROP TRIGGER immutable_effect_receipt_delete")
        with self.assertRaises(Exception):
            migrate_store_v1_to_v2(store)


if __name__ == '__main__':
    unittest.main(verbosity=2)
