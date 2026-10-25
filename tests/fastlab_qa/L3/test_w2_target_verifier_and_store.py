"""Тесты доверенного верификатора и W2 транзакционной схемы эффектов (L3 / W2)."""
import hashlib
from dataclasses import replace
from pathlib import Path
import pytest

from rai_fabric.store import FabricStore, FabricError
from rai_fabric.w2_migration import migrate_store_v1_to_v2
from rai_fabric.effect_receipt_contract import (
    EffectIntent, TargetEffectReceipt, ReceiptRejected
)
from rai_fabric.trusted_target_verifier import (
    LocalTrustedGrantRegistry, LocalTargetReadbackVerifier
)
from rai_fabric.w2_effect_bridge import (
    register_real_intent, commit_verified_effect_receipt, lease_real_task
)

DIGEST = "a" * 64
CONTENT_BODY = "hello-target-content"
CONTENT_SHA = hashlib.sha256(CONTENT_BODY.encode("utf-8")).hexdigest()
NOW = 1_800_000_100.0


@pytest.fixture
def w2_env(tmp_path):
    db_path = tmp_path / "test_w2_store.sqlite3"
    store = FabricStore(db_path, initialize=True)
    migrate_store_v1_to_v2(store)

    target_root = tmp_path / "target_root"
    target_root.mkdir()

    grant_reg = LocalTrustedGrantRegistry("RASSVET_DESKTOP", owner_verifying_key=b"test-owner-signing-key-32bytes!")
    target_ver = LocalTargetReadbackVerifier("RASSVET_DESKTOP")
    target_ver.register_target_root("approved-project", target_root)
    target_ver.register_target_revision("approved-project", "rev-01")

    yield store, grant_reg, target_ver, target_root, tmp_path
    store.close()


def make_valid_pair(task_id="task-001", operation_id="test_file.txt", target_id="approved-project"):
    intent = EffectIntent(
        task_id=task_id,
        provider="antigravity",
        target_id=target_id,
        host_id="RASSVET_DESKTOP",
        operation_id=operation_id,
        envelope_id="env-01",
        lease_epoch=1,
        lease_deadline_utc=NOW + 60,
        payload_sha256=DIGEST,
        owner_grant_ref=f"grant-{task_id}",
    )
    receipt = TargetEffectReceipt(
        task_id=task_id,
        provider="antigravity",
        target_id=target_id,
        host_id="RASSVET_DESKTOP",
        operation_id=operation_id,
        envelope_id="env-01",
        lease_epoch=1,
        verdict="APPLIED_VERIFIED",
        applied_sha256=DIGEST,
        target_revision="rev-01",
        readback_sha256=CONTENT_SHA,
        attestation_ref="attestation-ref-1",
        observed_at_utc=NOW - 1,
    )
    return intent, receipt


def test_w2_migration_idempotent(tmp_path):
    db_path = tmp_path / "migration.sqlite3"
    with FabricStore(db_path, initialize=True) as store:
        assert store.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "1"
        assert migrate_store_v1_to_v2(store) is True
        assert store.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"
        # Повторный вызов не ломает схему и возвращает False
        assert migrate_store_v1_to_v2(store) is False


def test_unauthorized_grant_rejected_at_intent_submission(w2_env):
    store, grant_reg, _, _, ws = w2_env
    intent, _ = make_valid_pair()
    # Мандат НЕ зарегистрирован в grant_reg
    with pytest.raises(ReceiptRejected, match="OWNER_GRANT_DENIED"):
        register_real_intent(store, intent, grant_reg, workspace=ws)
    assert store.list() == []


def test_payload_tamper_rejected_and_rolls_back(w2_env):
    store, grant_reg, target_ver, target_root, ws = w2_env
    intent, receipt = make_valid_pair()

    grant_reg.register_grant(intent.owner_grant_ref, intent.task_id, intent.target_id, intent.lease_deadline_utc)
    register_real_intent(store, intent, grant_reg, workspace=ws)

    # Записываем правильный файл
    (target_root / intent.operation_id).write_bytes(CONTENT_BODY.encode("utf-8"))

    # Подделка payload_sha256 в receipt
    tampered_receipt = replace(receipt, applied_sha256="c" * 64)
    with pytest.raises(ReceiptRejected, match="PAYLOAD_DIGEST_MISMATCH"):
        commit_verified_effect_receipt(
            store, intent, tampered_receipt, now_utc=NOW,
            grant_registry=grant_reg, target_verifier=target_ver
        )

    # Задача осталась в исходном QUEUED статусе без фиктивного завершения
    task = store.get(intent.task_id)
    assert task["status"] == "QUEUED"
    assert store.db.execute("SELECT COUNT(*) FROM effect_receipts").fetchone()[0] == 0


@pytest.mark.parametrize("bad_verdict", ["ACK", "QUEUED", "SUCCESS", "BLOCKED", "UNKNOWN"])
def test_non_applied_verdict_rejected(w2_env, bad_verdict):
    store, grant_reg, target_ver, target_root, ws = w2_env
    intent, receipt = make_valid_pair()

    grant_reg.register_grant(intent.owner_grant_ref, intent.task_id, intent.target_id, intent.lease_deadline_utc)
    register_real_intent(store, intent, grant_reg, workspace=ws)
    (target_root / intent.operation_id).write_bytes(CONTENT_BODY.encode("utf-8"))

    with pytest.raises(ReceiptRejected, match="NOT_TARGET_VERIFIED"):
        commit_verified_effect_receipt(
            store, intent, replace(receipt, verdict=bad_verdict),
            now_utc=NOW, grant_registry=grant_reg, target_verifier=target_ver
        )
    assert store.get(intent.task_id)["status"] == "QUEUED"


def test_stale_or_expired_lease_rejected(w2_env):
    store, grant_reg, target_ver, target_root, ws = w2_env
    intent, receipt = make_valid_pair()

    grant_reg.register_grant(intent.owner_grant_ref, intent.task_id, intent.target_id, intent.lease_deadline_utc)
    register_real_intent(store, intent, grant_reg, workspace=ws)
    (target_root / intent.operation_id).write_bytes(CONTENT_BODY.encode("utf-8"))

    # Время проверки наступило ПОСЛЕ истечения срока аренды
    with pytest.raises(ReceiptRejected, match="STALE_OR_FUTURE_EFFECT"):
        commit_verified_effect_receipt(
            store, intent, receipt, now_utc=intent.lease_deadline_utc + 10,
            grant_registry=grant_reg, target_verifier=target_ver
        )


def test_host_mismatch_rejected(w2_env):
    store, grant_reg, target_ver, target_root, ws = w2_env
    intent, receipt = make_valid_pair()

    grant_reg.register_grant(intent.owner_grant_ref, intent.task_id, intent.target_id, intent.lease_deadline_utc)
    register_real_intent(store, intent, grant_reg, workspace=ws)
    (target_root / intent.operation_id).write_bytes(CONTENT_BODY.encode("utf-8"))

    # Чужой хост в receipt
    with pytest.raises(ReceiptRejected, match="CORRELATION_MISMATCH_HOST_ID"):
        commit_verified_effect_receipt(
            store, intent, replace(receipt, host_id="OTHER_HOST"),
            now_utc=NOW, grant_registry=grant_reg, target_verifier=target_ver
        )


def test_duplicate_effect_replay_rejected(w2_env):
    store, grant_reg, target_ver, target_root, ws = w2_env
    intent, receipt = make_valid_pair()

    grant_reg.register_grant(intent.owner_grant_ref, intent.task_id, intent.target_id, intent.lease_deadline_utc)
    register_real_intent(store, intent, grant_reg, workspace=ws)
    lease_info = lease_real_task(store, intent)
    (target_root / intent.operation_id).write_bytes(CONTENT_BODY.encode("utf-8"))

    # Первый коммит проходит штатно
    ev1 = commit_verified_effect_receipt(
        store, intent, receipt, now_utc=NOW,
        grant_registry=grant_reg, target_verifier=target_ver,
        lease_token=lease_info["lease_token"]
    )
    assert ev1.classification == "EVIDENCE_ADMISSIBLE_NOT_QA_PASS"
    assert store.get(intent.task_id)["status"] == "COMPLETE"

    # Повторная посылка той же квитанции (Replay) категорически отклоняется
    with pytest.raises(ReceiptRejected, match="DUPLICATE_EFFECT_REPLAY"):
        commit_verified_effect_receipt(
            store, intent, receipt, now_utc=NOW,
            grant_registry=grant_reg, target_verifier=target_ver,
            lease_token=lease_info["lease_token"]
        )


def test_target_readback_content_mismatch_rejected(w2_env):
    store, grant_reg, target_ver, target_root, ws = w2_env
    intent, receipt = make_valid_pair()

    grant_reg.register_grant(intent.owner_grant_ref, intent.task_id, intent.target_id, intent.lease_deadline_utc)
    register_real_intent(store, intent, grant_reg, workspace=ws)

    # На диске файл с другим содержимым
    (target_root / intent.operation_id).write_bytes(b"tampered-disk-data")

    with pytest.raises(ReceiptRejected, match="TARGET_READBACK_MISMATCH"):
        commit_verified_effect_receipt(
            store, intent, receipt, now_utc=NOW,
            grant_registry=grant_reg, target_verifier=target_ver
        )


def test_direct_store_finish_without_effect_receipt_rejected(w2_env):
    store, grant_reg, _, _, ws = w2_env
    intent, _ = make_valid_pair()
    grant_reg.register_grant(intent.owner_grant_ref, intent.task_id, intent.target_id, intent.lease_deadline_utc)
    register_real_intent(store, intent, grant_reg, workspace=ws)

    # Попытка вызвать claim/finish напрямую на real provider без verified effect receipt
    with pytest.raises(FabricError, match="Реальный provider запрещён без verified target adapter/receipt"):
        store.claim("attacker", provider="antigravity")


def test_full_positive_w2_effect_cycle(w2_env):
    store, grant_reg, target_ver, target_root, ws = w2_env
    intent, receipt = make_valid_pair()

    grant_reg.register_grant(intent.owner_grant_ref, intent.task_id, intent.target_id, intent.lease_deadline_utc)
    register_real_intent(store, intent, grant_reg, workspace=ws)
    lease_info = lease_real_task(store, intent)

    (target_root / intent.operation_id).write_bytes(CONTENT_BODY.encode("utf-8"))

    evidence = commit_verified_effect_receipt(
        store, intent, receipt, now_utc=NOW,
        grant_registry=grant_reg, target_verifier=target_ver,
        lease_token=lease_info["lease_token"]
    )
    assert evidence.classification == "EVIDENCE_ADMISSIBLE_NOT_QA_PASS"
    assert evidence.task_id == intent.task_id
    assert evidence.readback_sha256 == CONTENT_SHA

    # Проверка состояния БД
    task = store.get(intent.task_id)
    assert task["status"] == "COMPLETE"
    raw_res = store.db.execute("SELECT result_json FROM tasks WHERE id=?", (intent.task_id,)).fetchone()[0]
    assert '"verdict":"PASS"' in raw_res
    assert '"status":"COMPLETE"' in raw_res

    receipt_rows = store.db.execute("SELECT * FROM effect_receipts").fetchall()
    assert len(receipt_rows) == 1
    assert receipt_rows[0]["verdict"] == "APPLIED_VERIFIED"
    assert receipt_rows[0]["applied_sha256"] == DIGEST
