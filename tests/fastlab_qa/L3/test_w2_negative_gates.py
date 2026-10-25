"""BPR5micro non-vacuous adversarial test suite for FASTLAB L3 Block C.
All negative tests verify specific failure modes and specific error codes
with otherwise valid, pinned revision, valid content, and (where applicable) active lease.
Only SQLite :memory: + TemporaryDirectory; no live provider/host/network.
"""
from __future__ import annotations
import hashlib
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from rai_fabric.store import FabricStore, FabricError
from rai_fabric.w2_migration import migrate_store_v1_to_v2
from rai_fabric.w2_effect_bridge import (
    register_real_intent, lease_real_task, commit_verified_effect_receipt
)
from rai_fabric.effect_receipt_contract import EffectIntent, TargetEffectReceipt, ReceiptRejected
from rai_fabric.trusted_target_verifier import LocalTrustedGrantRegistry, LocalTargetReadbackVerifier

NOW = 1_800_000_100.0
CONTENT = b'a real-looking local file'
DIGEST = hashlib.sha256(CONTENT).hexdigest()
PINNED_REVISION = "pinned-target-rev-01"
ATTESTATION_REF = "attestation-trusted-01"


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

    def submit(self, objective, provider, workspace, *, task_id=None, depends_on=None):
        t_id = task_id or f"task-{time.time()}"
        self.db.execute(
            'INSERT INTO tasks(id,objective,provider,workspace,status,updated_at) VALUES(?,?,?,?,?,?)',
            (t_id, objective, provider, workspace, 'QUEUED', time.time())
        )
        return {'id': t_id, 'status': 'QUEUED'}

    def _event(self, *args):
        pass

    def _checkpoint(self, *args):
        pass


class CandidateGateRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='raif-w2-red-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'approved'
        self.root.mkdir()
        # Intent and receipt have valid, fully correlated parameters with PINNED_REVISION
        self.intent = EffectIntent(
            'test-task', 'antigravity', 'approved-target', 'RASSVET_DESKTOP',
            'file.txt', 'envelope-1', 1, NOW + 100, 'a' * 64, 'self-issued-grant'
        )
        self.receipt = TargetEffectReceipt(
            'test-task', 'antigravity', 'approved-target', 'RASSVET_DESKTOP',
            'file.txt', 'envelope-1', 1, 'APPLIED_VERIFIED', 'a' * 64, PINNED_REVISION,
            DIGEST, ATTESTATION_REF, NOW - 1
        )
        (self.root / 'file.txt').write_bytes(CONTENT)
        self.owner_key = b"test-owner-signing-key-32bytes!"
        self.grant = LocalTrustedGrantRegistry("RASSVET_DESKTOP", owner_verifying_key=self.owner_key)
        self.grant.register_grant(
            self.intent.owner_grant_ref, self.intent.task_id,
            self.intent.target_id, self.intent.lease_deadline_utc
        )
        self.verifier = LocalTargetReadbackVerifier()
        self.verifier.register_target_root(self.intent.target_id, self.root)
        self.verifier.register_target_revision(self.intent.target_id, PINNED_REVISION)

    def fresh_store(self):
        store = FabricStoreMirror()
        migrate_store_v1_to_v2(store)
        register_real_intent(store, self.intent, self.grant, workspace=self.root)
        self.addCleanup(store.db.close)
        return store

    def test_sibling_root_prefix_escape_must_be_denied(self):
        """Проверка path traversal: выход за пределы root отклоняется даже при валидной ревизии."""
        sibling = self.root.parent / 'approved_mimic'
        sibling.mkdir()
        (sibling / 'file.txt').write_bytes(CONTENT)
        sub = '..' + '/' + sibling.name + '/file.txt'
        intent = replace(self.intent, operation_id=sub)
        receipt = replace(self.receipt, operation_id=sub)
        self.verifier.register_target_revision(self.intent.target_id, PINNED_REVISION, operation_id=sub)
        # Должен вернуть None строго из-за невалидного пути (semantic path containment), а не из-за ревизии
        self.assertIsNone(self.verifier.verify_target(intent, receipt))

    def test_unverified_target_revision_must_be_denied(self):
        """Проверка ревизий: отклоняются как плейсхолдеры, так и незарегистрированные ревизии."""
        # 1. Явный unverified плейсхолдер
        unverified_receipt = replace(self.receipt, target_revision="UNVERIFIED_REVISION")
        self.assertIsNone(self.verifier.verify_target(self.intent, unverified_receipt))

        # 2. Несовпадающая ревизия
        mismatched_receipt = replace(self.receipt, target_revision="other-revision")
        self.assertIsNone(self.verifier.verify_target(self.intent, mismatched_receipt))

        # 3. Незарегистрированная ревизия на чистом верификаторе (fail-closed)
        fresh_ver = LocalTargetReadbackVerifier()
        fresh_ver.register_target_root(self.intent.target_id, self.root)
        self.assertIsNone(fresh_ver.verify_target(self.intent, self.receipt))

    def test_unleased_queued_task_cannot_commit_real_pass(self):
        """Неарендованная задача в статусе QUEUED не может совершить переход в COMPLETE/PASS."""
        store = self.fresh_store()
        row = store.db.execute("SELECT status,lease_epoch,lease_owner FROM tasks").fetchone()
        self.assertEqual((row['status'], row['lease_epoch'], row['lease_owner']), ('QUEUED', 0, None))
        
        # Должен выбросить именно TASK_NOT_RUNNING (non-vacuous check)
        with self.assertRaisesRegex(ReceiptRejected, "TASK_NOT_RUNNING"):
            commit_verified_effect_receipt(
                store, self.intent, self.receipt, now_utc=NOW,
                grant_registry=self.grant, target_verifier=self.verifier
            )
        # Состояние базы данных не должно измениться
        self.assertEqual(store.db.execute('SELECT status FROM tasks').fetchone()[0], 'QUEUED')
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM effect_receipts').fetchone()[0], 0)

    def test_cancelled_task_cannot_reanimate_into_complete(self):
        """Отменённая задача не может быть реанимирована в COMPLETE."""
        store = self.fresh_store()
        lease_info = lease_real_task(store, self.intent)
        store.db.execute("UPDATE tasks SET status='CANCELLED',cancel_requested=1 WHERE id=?", (self.intent.task_id,))
        
        # Должен выбросить именно TASK_CANCELLED
        with self.assertRaisesRegex(ReceiptRejected, "TASK_CANCELLED"):
            commit_verified_effect_receipt(
                store, self.intent, self.receipt, now_utc=NOW,
                grant_registry=self.grant, target_verifier=self.verifier,
                lease_token=lease_info["lease_token"]
            )
        self.assertEqual(store.db.execute('SELECT status FROM tasks').fetchone()[0], 'CANCELLED')
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM effect_receipts').fetchone()[0], 0)

    def test_mismatched_persisted_intent_must_be_denied(self):
        """Подделка данных в effect_intents отклоняется даже при активной аренде."""
        store = self.fresh_store()
        lease_info = lease_real_task(store, self.intent)
        store.db.execute(
            "UPDATE effect_intents SET payload_sha256=? WHERE task_id=?",
            ('f' * 64, self.intent.task_id)
        )
        
        # Должен выбросить именно PERSISTED_INTENT_TAMPERED
        with self.assertRaisesRegex(ReceiptRejected, "PERSISTED_INTENT_TAMPERED"):
            commit_verified_effect_receipt(
                store, self.intent, self.receipt, now_utc=NOW,
                grant_registry=self.grant, target_verifier=self.verifier,
                lease_token=lease_info["lease_token"]
            )
        # Задача остаётся в статусе RUNNING, квитанция не зафиксирована
        self.assertEqual(store.db.execute('SELECT status FROM tasks').fetchone()[0], 'RUNNING')
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM effect_receipts').fetchone()[0], 0)

    def test_corrupt_v2_missing_immutable_trigger_must_not_be_accepted(self):
        """Повреждение схемы v2 (удаление триггера неизменяемости) приводит к отклонению миграции."""
        store = FabricStoreMirror()
        self.addCleanup(store.db.close)
        migrate_store_v1_to_v2(store)
        store.db.execute("DROP TRIGGER immutable_effect_receipt_delete")
        with self.assertRaisesRegex(FabricError, "immutable_effect_receipt_delete"):
            migrate_store_v1_to_v2(store)

    def test_mismatched_lease_token_must_be_denied(self):
        """Попытка коммита без токена аренды или с чужим токеном категорически отклоняется."""
        store = self.fresh_store()
        lease_info = lease_real_task(store, self.intent)
        
        # 1. Отсутствие токена аренды
        with self.assertRaisesRegex(ReceiptRejected, "MISSING_LEASE_TOKEN"):
            commit_verified_effect_receipt(
                store, self.intent, self.receipt, now_utc=NOW,
                grant_registry=self.grant, target_verifier=self.verifier,
                lease_token=None
            )
        
        # 2. Неверный токен аренды
        with self.assertRaisesRegex(ReceiptRejected, "LEASE_TOKEN_MISMATCH"):
            commit_verified_effect_receipt(
                store, self.intent, self.receipt, now_utc=NOW,
                grant_registry=self.grant, target_verifier=self.verifier,
                lease_token="attacker-wrong-token-abc"
            )
        self.assertEqual(store.db.execute('SELECT status FROM tasks').fetchone()[0], 'RUNNING')
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM effect_receipts').fetchone()[0], 0)

    def test_null_or_empty_lease_hash_bypass_must_be_denied(self):
        """Проверка P0-B: задача в статусе RUNNING с lease_hash=NULL не должна совершать переход в COMPLETE без токена."""
        store = self.fresh_store()
        lease_info = lease_real_task(store, self.intent)
        # Обнуляем lease_hash в БД для симуляции обхода
        store.db.execute("UPDATE tasks SET lease_hash=NULL WHERE id=?", (self.intent.task_id,))
        with self.assertRaisesRegex(ReceiptRejected, "MISSING_OR_INVALID_LEASE_HASH"):
            commit_verified_effect_receipt(
                store, self.intent, self.receipt, now_utc=NOW,
                grant_registry=self.grant, target_verifier=self.verifier,
                lease_token=None
            )
        self.assertEqual(store.db.execute('SELECT status FROM tasks').fetchone()[0], 'RUNNING')
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM effect_receipts').fetchone()[0], 0)

    def test_mismatched_lease_owner_in_store_must_be_denied(self):
        """Проверка P0-B: несовпадение владельца аренды (lease_owner) блокирует коммит через CAS."""
        store = self.fresh_store()
        lease_info = lease_real_task(store, self.intent)
        store.db.execute("UPDATE tasks SET lease_owner='other-owner' WHERE id=?", (self.intent.task_id,))
        with self.assertRaisesRegex(ReceiptRejected, "CAS_GUARD_FAILED|LEASE_OWNER_MISMATCH"):
            commit_verified_effect_receipt(
                store, self.intent, self.receipt, now_utc=NOW,
                grant_registry=self.grant, target_verifier=self.verifier,
                lease_token=lease_info["lease_token"]
            )
        self.assertEqual(store.db.execute('SELECT status FROM tasks').fetchone()[0], 'RUNNING')
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM effect_receipts').fetchone()[0], 0)

    def test_self_issued_or_unauthorized_owner_grant_must_be_denied(self):
        """Проверка P0-A: самовыданный грант с дефолтным ключом или чужой подписью отклоняется."""
        # 1. Подделка подписи гранта
        unauthorized_grant = replace(self.grant._grants[self.intent.owner_grant_ref], signature="bad-signature-" + "0" * 48)
        self.grant._grants[self.intent.owner_grant_ref] = unauthorized_grant
        self.assertFalse(self.grant.authorize(self.intent))

        # 2. Использование дефолтного публичного ключа для реального провайдера запрещено
        default_registry = LocalTrustedGrantRegistry("RASSVET_DESKTOP")
        default_registry.register_grant(
            self.intent.owner_grant_ref, self.intent.task_id,
            self.intent.target_id, self.intent.lease_deadline_utc
        )
        store = FabricStoreMirror()
        migrate_store_v1_to_v2(store)
        self.addCleanup(store.db.close)
        with self.assertRaisesRegex(ReceiptRejected, "DEFAULT_SIGNING_KEY_FORBIDDEN|OWNER_GRANT_DENIED"):
            register_real_intent(store, self.intent, default_registry, workspace=self.root)

    def test_unauthorized_actor_cannot_acquire_real_lease(self):
        """Проверка P0-C: неавторизованный вызывающий процесс без валидного мандата не может перевести задачу в RUNNING."""
        store = self.fresh_store()
        tampered_intent = replace(self.intent, payload_sha256="b" * 64)
        with self.assertRaisesRegex(FabricError, "PERSISTED_INTENT_MISMATCH|UNAUTHORIZED_CLAIM"):
            lease_real_task(store, tampered_intent, grant_registry=self.grant)

    def test_evidence_admissible_without_owner_finalization_mandate_does_not_promote_task_to_pass(self):
        """Проверка P0-D: квитанция со скоупом EVIDENCE_ADMISSIBLE_ONLY не переводит задачу в COMPLETE/PASS."""
        store = self.fresh_store()
        lease_info = lease_real_task(store, self.intent, grant_registry=self.grant)
        # Регистрируем мандат со скоупом EVIDENCE_ADMISSIBLE_ONLY с валидной HMAC подписью
        self.grant.register_grant(
            self.intent.owner_grant_ref, self.intent.task_id,
            self.intent.target_id, self.intent.lease_deadline_utc,
            mandate_scope="EVIDENCE_ADMISSIBLE_ONLY"
        )
        evidence = commit_verified_effect_receipt(
            store, self.intent, self.receipt, now_utc=NOW,
            grant_registry=self.grant, target_verifier=self.verifier,
            lease_token=lease_info["lease_token"]
        )
        self.assertEqual(evidence.classification, "EVIDENCE_ADMISSIBLE_NOT_QA_PASS")
        task_status = store.db.execute('SELECT status FROM tasks WHERE id=?', (self.intent.task_id,)).fetchone()[0]
        self.assertNotEqual(task_status, "COMPLETE")
        self.assertEqual(task_status, "RUNNING")
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM effect_receipts').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
