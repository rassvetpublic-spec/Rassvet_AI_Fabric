"""L3 Block C security RED->GREEN regressions on disposable FabricStore.

No production DB, network/runner service, real provider or host authority.
All tests are source-only SELF_QA; admission must never become real PASS.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from rai_fabric.effect_receipt_contract import (
    EffectIntent, TargetEffectReceipt, ReceiptRejected, verify_effect_receipt,
)
from rai_fabric.store import FabricError, FabricStore
from rai_fabric.trusted_target_verifier import (
    LocalTargetReadbackVerifier, LocalTrustedGrantRegistry, VerifierError,
)
from rai_fabric.w2_effect_bridge import register_real_intent, commit_verified_effect_receipt
from rai_fabric.w2_migration import migrate_store_v1_to_v2

NOW = 1_800_000_100.0
BODY = b"authorized-looking test content"
CONTENT_SHA = hashlib.sha256(BODY).hexdigest()


@pytest.fixture
def source_env(tmp_path):
    root = tmp_path / "approved"
    root.mkdir()
    (root / "file.txt").write_bytes(BODY)
    store = FabricStore(tmp_path / "w2.sqlite3", initialize=True)
    migrate_store_v1_to_v2(store)
    intent = EffectIntent(
        task_id="w2-test-task", provider="antigravity", target_id="approved-target",
        host_id="RASSVET_DESKTOP", operation_id="file.txt", envelope_id="w2-env-1",
        lease_epoch=1, lease_deadline_utc=NOW + 60, payload_sha256="a" * 64,
        owner_grant_ref="selftest-grant",
    )
    receipt = TargetEffectReceipt(
        task_id=intent.task_id, provider=intent.provider, target_id=intent.target_id,
        host_id=intent.host_id, operation_id=intent.operation_id,
        envelope_id=intent.envelope_id, lease_epoch=intent.lease_epoch,
        verdict="APPLIED_VERIFIED", applied_sha256=intent.payload_sha256,
        target_revision="sha256:" + CONTENT_SHA, readback_sha256=CONTENT_SHA,
        attestation_ref="selftest-unsigned", observed_at_utc=NOW - 1,
    )
    grants = LocalTrustedGrantRegistry(
        expected_host_id="RASSVET_DESKTOP",
        verify_issuer=lambda grant, _intent: grant.issuer_ref == "OFFLINE_TEST_ONLY",
    )
    grants.register_grant(
        intent.owner_grant_ref, intent.task_id, intent.target_id, intent.lease_deadline_utc,
        provider=intent.provider, operation_id=intent.operation_id,
        envelope_id=intent.envelope_id, payload_sha256=intent.payload_sha256,
        issuer_ref="OFFLINE_TEST_ONLY",
    )
    verifier = LocalTargetReadbackVerifier()
    verifier.register_target_root(intent.target_id, root)
    yield store, root, intent, receipt, grants, verifier
    store.close()


def staged(env):
    store, root, intent, receipt, grants, verifier = env
    register_real_intent(store, intent, grants, workspace=root, shadow_only=True)
    return store, root, intent, receipt, grants, verifier


def try_commit(env, **kwargs):
    store, _, intent, receipt, grants, verifier = env
    return commit_verified_effect_receipt(
        store, intent, receipt, now_utc=NOW, grant_registry=grants,
        target_verifier=verifier, **kwargs,
    )


def test_sibling_prefix_escape_is_denied(source_env):
    _, root, intent, receipt, _, verifier = source_env
    sibling = root.parent / "approved_mimic"
    sibling.mkdir()
    (sibling / "file.txt").write_bytes(BODY)
    adversarial = replace(intent, operation_id="../approved_mimic/file.txt")
    fake_receipt = replace(receipt, operation_id=adversarial.operation_id)
    assert verifier.verify_target(adversarial, fake_receipt) is None


def test_false_receipt_revision_is_denied(source_env):
    _, _, intent, receipt, _, verifier = source_env
    assert verifier.verify_target(intent, replace(receipt, target_revision="UNVERIFIED_REVISION")) is None


def test_queued_real_task_cannot_become_complete(source_env):
    env = staged(source_env)
    with pytest.raises(ReceiptRejected, match="ACTIVE_RUNNING_LEASE_REQUIRED"):
        try_commit(env)
    assert env[0].get(env[2].task_id)["status"] == "QUEUED"
    assert env[0].db.execute("SELECT COUNT(*) FROM effect_receipts").fetchone()[0] == 0


def test_cancelled_real_task_cannot_be_reanimated(source_env):
    env = staged(source_env)
    env[0].db.execute("UPDATE tasks SET status='CANCELLED',cancel_requested=1")
    with pytest.raises(ReceiptRejected, match="CANCELLED_EFFECT_DENIED"):
        try_commit(env)
    assert env[0].get(env[2].task_id)["status"] == "CANCELLED"


def test_persisted_intent_digest_cannot_be_swapped(source_env):
    env = staged(source_env)
    env[0].db.execute("UPDATE effect_intents SET payload_sha256=?", ("f" * 64,))
    with pytest.raises(ReceiptRejected, match="PERSISTED_INTENT_MISMATCH_PAYLOAD_SHA256"):
        try_commit(env)


def test_corrupt_v2_missing_immutable_trigger_is_rejected(source_env):
    store = source_env[0]
    store.db.execute("DROP TRIGGER immutable_effect_receipt_delete")
    with pytest.raises(FabricError, match="W2_SCHEMA_CORRUPT:trigger"):
        migrate_store_v1_to_v2(store)


def test_symlink_outside_root_cannot_be_read(source_env):
    _, root, intent, receipt, _, verifier = source_env
    outside = root.parent / "outside"
    outside.mkdir()
    (outside / "file.txt").write_bytes(BODY)
    path = root / "bridge"
    try:
        path.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not enabled for this Windows test identity")
    adversarial = replace(intent, operation_id="bridge/file.txt")
    fake_receipt = replace(receipt, operation_id=adversarial.operation_id)
    assert verifier.verify_target(adversarial, fake_receipt) is None


@pytest.mark.parametrize("bad_path", ["../file.txt", "/tmp/file.txt", "file.txt:ADS", "C:/Windows/test.txt", "\\\\server\\share\\a", "..\\file.txt"])
def test_absolute_ads_windows_or_parent_path_denied(source_env, bad_path):
    _, _, intent, receipt, _, verifier = source_env
    adversarial = replace(intent, operation_id=bad_path)
    fake_receipt = replace(receipt, operation_id=bad_path)
    assert verifier.verify_target(adversarial, fake_receipt) is None


def test_self_registered_grant_without_external_verifier_is_not_authority(source_env):
    _, _, intent, _, _, _ = source_env
    grants = LocalTrustedGrantRegistry()
    grants.register_grant(
        intent.owner_grant_ref, intent.task_id, intent.target_id, intent.lease_deadline_utc,
        provider=intent.provider, operation_id=intent.operation_id,
        envelope_id=intent.envelope_id, payload_sha256=intent.payload_sha256,
        issuer_ref="self-issued",
    )
    assert grants.authorize(intent) is False


def test_synthetic_sink_does_not_attest_production_file(source_env):
    _, _, intent, receipt, _, verifier = source_env
    fake = LocalTargetReadbackVerifier()
    fake.register_synthetic_sink(intent.target_id, {intent.operation_id: BODY.decode("utf-8")})
    assert fake.verify_target(intent, receipt) is None


def test_full_intent_provider_and_operation_binding(source_env):
    env = staged(source_env)
    env[0].db.execute("UPDATE effect_intents SET provider='codex-app'")
    with pytest.raises(ReceiptRejected, match="PERSISTED_INTENT_MISMATCH_PROVIDER"):
        try_commit(env)


def test_staged_operation_tampering_is_rejected(source_env):
    env = staged(source_env)
    env[0].db.execute("UPDATE effect_operations SET payload_sha256=?", ("b" * 64,))
    with pytest.raises(ReceiptRejected, match="PERSISTED_OPERATION_MISMATCH_PAYLOAD_SHA256"):
        try_commit(env)


def test_active_lease_owner_token_and_host_grant_remain_separate(source_env):
    env = staged(source_env)
    store, root, intent, receipt, grants, verifier = env
    token = "selftest-lease-only"
    store.db.execute("""
        UPDATE tasks SET status='RUNNING', lease_epoch=1, lease_owner='owner-selftest',
            lease_hash=?, lease_deadline=?, cancel_requested=0
        WHERE id=?
    """, (hashlib.sha256(token.encode()).hexdigest(), NOW + 60, intent.task_id))
    with pytest.raises(ReceiptRejected, match="LEASE_PROOF_MISSING"):
        try_commit(env)
    with pytest.raises(ReceiptRejected, match="LEASE_TOKEN_INVALID"):
        try_commit(env, lease_owner="owner-selftest", lease_token="wrong-token")
    with pytest.raises(ReceiptRejected, match="HOST_EFFECT_AUTHORITY_NOT_IMPLEMENTED"):
        try_commit(env, lease_owner="owner-selftest", lease_token=token)
    assert store.get(intent.task_id)["status"] == "RUNNING"
    assert store.db.execute("SELECT COUNT(*) FROM effect_receipts").fetchone()[0] == 0


def test_missing_required_index_rejected(source_env):
    store = source_env[0]
    store.db.execute("DROP INDEX idx_effect_task")
    with pytest.raises(FabricError, match="W2_SCHEMA_CORRUPT:index"):
        migrate_store_v1_to_v2(store)


def test_preexisting_corrupt_table_rolls_back_migration(tmp_path):
    with FabricStore(tmp_path / "corrupt-v1.sqlite3", initialize=True) as store:
        store.db.execute("CREATE TABLE effect_intents(task_id TEXT PRIMARY KEY)")
        with pytest.raises(FabricError, match="W2_SCHEMA_CORRUPT"):
            migrate_store_v1_to_v2(store)
        assert store.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "1"
        # All new objects created in that transaction must also roll back.
        assert store.db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='effect_receipts'"
        ).fetchone()[0] == 0


def test_verified_file_evidence_is_only_admissible_not_pass(source_env):
    store, root, intent, receipt, grants, verifier = source_env
    source = verify_effect_receipt(
        intent, receipt, now_utc=NOW,
        authorize_grant=grants.authorize, verify_target=verifier.verify_target,
    )
    assert source.classification == "EVIDENCE_ADMISSIBLE_NOT_QA_PASS"
    assert source.readback_sha256 == CONTENT_SHA
    assert store.list() == []
