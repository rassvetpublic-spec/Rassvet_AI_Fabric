"""Independent regression tests with a disposable workspace and database."""
import concurrent.futures
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from rai_fabric.store import FabricError, FabricStore, checksum
from rai_fabric.worker import run_one


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'state.db'
        self.db = FabricStore(self.path, initialize=True)
        self.addCleanup(self.db.close)

    def task(self, task_id='one', depends_on=None, provider='mock'):
        return self.db.submit('Original task', provider, str(self.root), task_id=task_id, depends_on=depends_on)

    def test_init_requires_explicit_action(self):
        with self.assertRaises(FabricError):
            FabricStore(self.root / 'missing.db')

    def test_schema_version(self):
        self.assertEqual(self.db.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '1')

    def test_submission_creates_checkpoint(self):
        self.task()
        cp = self.db.latest_checkpoint('one')
        self.assertEqual(cp['stage'], 'SUBMITTED')
        self.assertEqual(cp['cursor'], 'DISPATCH')
        self.assertEqual(cp['sha256'], checksum({k: cp[k] for k in ('task_id','timestamp','stage','verdict','cursor','evidence')}))

    def test_submit_idempotent(self):
        self.task()
        self.task()
        self.assertEqual(len(self.db.list()), 1)
        with self.assertRaises(FabricError):
            self.db.submit('different objective', 'mock', str(self.root), task_id='one')

    def test_provider_validation(self):
        with self.assertRaises(FabricError):
            self.db.submit('hey', 'api-billed', str(self.root))

    def test_self_dependency_is_rejected(self):
        with self.assertRaises(FabricError):
            self.task('one', ['one'])

    def test_missing_dependency_rejected(self):
        with self.assertRaises(FabricError):
            self.task('one', ['ghost'])

    def test_dependency_waits(self):
        self.task('one')
        self.task('two', ['one'])
        worker = self.db.claim('worker', lease_seconds=120)
        self.assertEqual(worker['task_id'], 'one')
        self.assertIsNone(self.db.claim('worker2'))
        self.db.finish('one', 'worker', worker['lease_token'], verdict='PASS', response='ok', evidence={})
        second = self.db.claim('worker2')
        self.assertEqual(second['task_id'], 'two')

    def test_lease_unique_and_non_public(self):
        self.task()
        claim = self.db.claim('a')
        self.assertIsNotNone(claim['lease_token'])
        self.assertIsNone(self.db.claim('b'))
        self.assertNotIn('lease_hash', self.db.get('one'))
        self.assertNotIn('lease_token', json.dumps(self.db.list()))

    def test_wrong_token(self):
        self.task()
        self.db.claim('worker')
        with self.assertRaises(FabricError):
            self.db.checkpoint('one', 'worker', 'WRONG', 'S', 'NEXT', {})

    def test_wrong_worker(self):
        self.task()
        w = self.db.claim('worker')
        with self.assertRaises(FabricError):
            self.db.finish('one', 'other', w['lease_token'], verdict='PASS', response='ok', evidence={})

    def test_heartbeat_extends_lease(self):
        self.task()
        w = self.db.claim('worker', lease_seconds=5)
        result = self.db.heartbeat('one', 'worker', w['lease_token'], lease_seconds=30)
        self.assertGreater(result['lease_deadline'], w['lease_deadline'])

    def test_checkpoint_retrievable(self):
        self.task()
        w = self.db.claim('worker')
        self.db.checkpoint('one', 'worker', w['lease_token'], 'VALIDATED', 'APPLY', {'tests': 7}, verdict='PASS')
        self.assertEqual(self.db.get('one')['checkpoint']['evidence']['tests'], 7)
        self.assertEqual(self.db.get('one')['checkpoint']['cursor'], 'APPLY')

    def test_finishing_ends_lease(self):
        self.task()
        w = self.db.claim('worker')
        final = self.db.finish('one', 'worker', w['lease_token'], verdict='PASS', response='OK', evidence={'test': 'pass'})
        self.assertEqual(final['status'], 'COMPLETE')
        self.assertEqual(final['checkpoint']['cursor'], 'REVIEW')
        self.assertEqual(self.db.result('one')['response'], 'OK')
        with self.assertRaises(FabricError):
            self.db.heartbeat('one', 'worker', w['lease_token'])

    def test_failure_requires_operator_reconciliation(self):
        self.task()
        w = self.db.claim('worker')
        self.db.finish('one', 'worker', w['lease_token'], verdict='BLOCKED', response='error', evidence={})
        with self.assertRaises(FabricError):
            self.db.requeue('one', acknowledgement='ok')
        self.db.requeue('one', acknowledgement='подтверждено отсутствие побочных внешних действий')
        self.assertEqual(self.db.get('one')['status'], 'QUEUED')
        w2 = self.db.claim('worker')
        self.assertNotEqual(w['lease_token'], w2['lease_token'])
        self.assertGreater(w2['lease_epoch'], w['lease_epoch'])

    def test_recover_expired_does_not_reexecute(self):
        self.task()
        w = self.db.claim('worker')
        self.db.db.execute("UPDATE tasks SET lease_deadline=? WHERE id='one'", (time.time()-1,))
        self.assertEqual(self.db.recover(), ['one'])
        self.assertEqual(self.db.get('one')['status'], 'BLOCKED')
        self.assertEqual(self.db.get('one')['checkpoint']['cursor'], 'VERIFY_EXTERNAL_SIDE_EFFECTS')
        self.assertIsNone(self.db.claim('anyone'))
        with self.assertRaises(FabricError):
            self.db.finish('one', 'worker', w['lease_token'], verdict='PASS', response='x', evidence={})

    def test_cancel_queued_immediate(self):
        self.task()
        self.db.request_cancel('one')
        self.assertEqual(self.db.get('one')['status'], 'CANCELLED')
        self.assertIsNone(self.db.claim('worker'))

    def test_cancel_running_needs_worker_acknowledgement(self):
        self.task()
        w = self.db.claim('worker')
        self.db.request_cancel('one')
        self.assertEqual(self.db.get('one')['status'], 'RUNNING')
        self.assertEqual(self.db.get('one')['cancel_requested'], 1)
        with self.assertRaises(FabricError):
            self.db.heartbeat('one', 'worker', w['lease_token'])
        self.assertEqual(self.db.confirm_cancel('one', 'worker', w['lease_token'])['status'], 'CANCELLED')

    def test_checkpoint_integrity_fail_closed(self):
        self.task()
        self.db.db.execute("UPDATE checkpoints SET cursor='FRAUD' WHERE task_id='one'")
        with self.assertRaises(FabricError):
            self.db.latest_checkpoint('one')

    def test_event_history(self):
        self.task()
        self.db.claim('worker')
        self.assertTrue(any(e['type'] == 'SUBMITTED' for e in self.db.events('one')))
        self.assertTrue(any(e['type'] == 'CLAIMED' for e in self.db.events('one')))

    def test_mock_provider_does_not_call_cloud(self):
        self.task()
        result = run_one(self.db, 'mock')
        self.assertEqual(result['status'], 'COMPLETE')
        events = self.db.events('one')
        self.assertTrue(any(e['type'] == 'FINISHED' for e in events))
        self.assertTrue(result['checkpoint']['evidence']['simulation'])

    def test_codex_driver_blocks_without_claim(self):
        self.task('one', provider='codex-app')
        with self.assertRaises(FabricError):
            run_one(self.db, 'codex-app')
        self.assertEqual(self.db.get('one')['status'], 'QUEUED')

    def test_antigravity_requires_opt_in_before_claim(self):
        self.task('one', provider='antigravity')
        with self.assertRaises(FabricError):
            run_one(self.db, 'antigravity')
        self.assertEqual(self.db.get('one')['status'], 'QUEUED')

    def test_two_processes_cannot_claim_one_task(self):
        self.task()
        def claim(i):
            with FabricStore(self.path) as s:
                return s.claim(f'worker-{i}')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            claimed = list(pool.map(claim, range(8)))
        self.assertEqual(sum(bool(v) for v in claimed), 1)


if __name__ == '__main__':
    unittest.main()
