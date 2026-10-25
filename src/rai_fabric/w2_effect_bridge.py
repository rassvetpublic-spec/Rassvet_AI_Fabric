"""W2 Effect Bridge: безопасное проведение реальных эффектов через доверенный верификатор.

Инварианты:
1. Replay/дубликат операции категорически отклоняется.
2. Stale epoch (несовпадающая эпоха аренды) отклоняется.
3. Прямой finish(PASS) без проверенной квитанции заблокирован.
4. Откат при ошибке сохраняет статус QUEUED без утечек.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from .effect_receipt_contract import (
    EffectIntent,
    TargetEffectReceipt,
    AdmissibleEvidence,
    ReceiptRejected,
    verify_effect_receipt,
)
from .store import FabricError, FabricStore, canonical
from .trusted_target_verifier import LocalTrustedGrantRegistry, LocalTargetReadbackVerifier


def register_real_intent(
    store: FabricStore,
    intent: EffectIntent,
    grant_registry: LocalTrustedGrantRegistry,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    """Регистрация намерения реального провайдера с фиксацией в effect_intents."""
    if not isinstance(intent, EffectIntent):
        raise ReceiptRejected("INVALID_INTENT_TYPE")

    # Проверка мандата владельца перед созданием задачи
    if not grant_registry.authorize(intent):
        raise ReceiptRejected("OWNER_GRANT_DENIED")

    ws = str(Path(workspace).resolve()) if workspace else str(Path.cwd().resolve())

    with store.atomic():
        now = time.time()
        # Создаем задачу в FabricStore
        task = store.submit(
            objective=f"Real task: {intent.operation_id} on {intent.target_id}",
            provider=intent.provider,
            workspace=ws,
            task_id=intent.task_id,
        )

        # Сохраняем intent в effect_intents
        store.db.execute("""
            INSERT INTO effect_intents (
                task_id, provider, target_id, host_id, operation_id, envelope_id,
                lease_epoch, lease_deadline_utc, payload_sha256, owner_grant_ref, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            intent.task_id, intent.provider, intent.target_id, intent.host_id,
            intent.operation_id, intent.envelope_id, intent.lease_epoch,
            intent.lease_deadline_utc, intent.payload_sha256, intent.owner_grant_ref, now
        ))

        # Заводим операцию в журнал effect_operations в статусе PREPARED
        store.db.execute("""
            INSERT INTO effect_operations (
                task_id, target_id, operation_id, payload_sha256, lease_epoch,
                expected_revision, phase, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?)
        """, (
            intent.task_id, intent.target_id, intent.operation_id,
            intent.payload_sha256, intent.lease_epoch, "initial", now, now
        ))

        return task


def lease_real_task(
    store: FabricStore,
    intent: EffectIntent,
    owner: str = "antigravity",
    lease_token: str = "w2-token-secret-1234",
) -> dict[str, Any]:
    """Авторизованный W2 lease gate: перевод задачи реального провайдера в статус RUNNING."""
    with store.atomic():
        task_row = store.db.execute("SELECT * FROM tasks WHERE id=?", (intent.task_id,)).fetchone()
        if not task_row:
            raise FabricError("TASK_NOT_FOUND")
        if task_row["status"] != "QUEUED":
            raise FabricError(f"TASK_NOT_QUEUED: {task_row['status']}")
        if task_row["cancel_requested"] != 0:
            raise FabricError("TASK_CANCELLED")

        intent_row = store.db.execute(
            "SELECT * FROM effect_intents WHERE task_id=?", (intent.task_id,)
        ).fetchone()
        if not intent_row:
            raise FabricError("INTENT_NOT_REGISTERED")

        now = time.time()
        digest = hashlib.sha256(lease_token.encode()).hexdigest()
        store.db.execute("""
            UPDATE tasks
            SET status='RUNNING', lease_owner=?, lease_hash=?, lease_epoch=?,
                lease_deadline=?, attempt=attempt+1, updated_at=?
            WHERE id=? AND status='QUEUED'
        """, (owner, digest, intent.lease_epoch, intent.lease_deadline_utc, now, intent.task_id))

        store._event(intent.task_id, "CLAIMED_REAL_TASK", {"owner": owner, "epoch": intent.lease_epoch})
        store._checkpoint(intent.task_id, "DISPATCHED_REAL_TASK", "PARTIAL", "EXECUTE",
                          {"owner": owner, "epoch": intent.lease_epoch})
        return {
            "task_id": intent.task_id,
            "lease_token": lease_token,
            "lease_epoch": intent.lease_epoch,
            "lease_deadline": intent.lease_deadline_utc,
            "provider": intent.provider,
            "owner": owner,
        }


def commit_verified_effect_receipt(
    store: FabricStore,
    intent: EffectIntent,
    receipt: TargetEffectReceipt,
    *,
    now_utc: float,
    grant_registry: LocalTrustedGrantRegistry,
    target_verifier: LocalTargetReadbackVerifier,
) -> AdmissibleEvidence:
    """Атомарная валидация и коммит эффекта в W2 FabricStore."""
    # 1. Строгая криптографическая валидация через контракт
    evidence = verify_effect_receipt(
        intent,
        receipt,
        now_utc=now_utc,
        authorize_grant=grant_registry.authorize,
        verify_target=target_verifier.verify_target,
    )

    # 2. Атомарная фиксация в хранилище с защитой аренды и статуса
    with store.atomic():
        # Защита от повтора/replay
        existing_receipt = store.db.execute(
            "SELECT 1 FROM effect_receipts WHERE target_id=? AND operation_id=?",
            (receipt.target_id, receipt.operation_id),
        ).fetchone()
        if existing_receipt:
            raise ReceiptRejected("DUPLICATE_EFFECT_REPLAY")

        # Проверяем наличие задачи
        task_row = store.db.execute("SELECT * FROM tasks WHERE id=?", (intent.task_id,)).fetchone()
        if not task_row:
            raise ReceiptRejected("TASK_NOT_FOUND")

        # Защита от отмены задачи
        if task_row["cancel_requested"] != 0 or task_row["status"] == "CANCELLED":
            raise ReceiptRejected("TASK_CANCELLED")

        # Проверка зарегистрированного намерения (persisted effect_intents)
        intent_row = store.db.execute(
            "SELECT * FROM effect_intents WHERE task_id=?", (intent.task_id,)
        ).fetchone()
        if not intent_row:
            raise ReceiptRejected("INTENT_NOT_FOUND")
        if (
            intent_row["payload_sha256"] != intent.payload_sha256
            or intent_row["target_id"] != intent.target_id
            or intent_row["host_id"] != intent.host_id
            or intent_row["operation_id"] != intent.operation_id
            or intent_row["owner_grant_ref"] != intent.owner_grant_ref
            or intent_row["lease_epoch"] != receipt.lease_epoch
            or intent_row["provider"] != intent.provider
            or intent_row["envelope_id"] != intent.envelope_id
        ):
            raise ReceiptRejected("PERSISTED_INTENT_TAMPERED")

        # Защита от непереведенной в исполнение / незанятой задачи (W2 lease fencing)
        if task_row["status"] != "RUNNING":
            raise ReceiptRejected("TASK_NOT_RUNNING")

        if task_row["lease_epoch"] != receipt.lease_epoch or task_row["lease_epoch"] <= 0:
            raise ReceiptRejected("STALE_LEASE_EPOCH")

        if task_row["lease_owner"] is None:
            raise ReceiptRejected("TASK_UNLEASED")

        if task_row["lease_deadline"] is not None and task_row["lease_deadline"] < now_utc:
            raise ReceiptRejected("LEASE_EXPIRED")

        # Расчет evidence_sha256 для соответствия W2-чекам store.py
        receipt_dict = {
            "target_id": receipt.target_id,
            "operation_id": receipt.operation_id,
            "verdict": receipt.verdict,
            "revision": receipt.target_revision,
            "applied_sha256": receipt.applied_sha256,
            "readback_class": evidence.verifier_ref,
        }
        evidence_sha256 = hashlib.sha256(canonical(receipt_dict).encode("utf-8")).hexdigest()

        # Обновляем effect_operations
        store.db.execute("""
            UPDATE effect_operations
            SET phase='APPLIED_VERIFIED', updated_at=?
            WHERE target_id=? AND operation_id=?
        """, (now_utc, receipt.target_id, receipt.operation_id))

        # Вставляем неизменяемую квитанцию в effect_receipts
        store.db.execute("""
            INSERT INTO effect_receipts (
                target_id, operation_id, verdict, target_revision,
                applied_sha256, evidence_sha256, readback_class, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            receipt.target_id, receipt.operation_id, receipt.verdict,
            receipt.target_revision, receipt.applied_sha256, evidence_sha256,
            evidence.verifier_ref, now_utc
        ))

        # Переводим задачу в COMPLETE с признаком PASS через guarded CAS
        result_payload = canonical({
            "status": "COMPLETE",
            "verdict": "PASS",
            "evidence_classification": evidence.classification,
            "verifier_ref": evidence.verifier_ref,
            "readback_sha256": evidence.readback_sha256,
        })
        cursor = store.db.execute("""
            UPDATE tasks
            SET status='COMPLETE', result_json=?, updated_at=?,
                lease_owner=NULL, lease_hash=NULL, lease_deadline=NULL
            WHERE id=? AND status='RUNNING' AND lease_epoch=? AND cancel_requested=0
        """, (result_payload, now_utc, intent.task_id, receipt.lease_epoch))
        if cursor.rowcount != 1:
            raise ReceiptRejected("CAS_GUARD_FAILED")

        # Записываем событие и чекпойнт
        store._event(intent.task_id, "EFFECT_COMMITTED", {
            "operation_id": intent.operation_id,
            "verifier_ref": evidence.verifier_ref,
            "readback_sha256": evidence.readback_sha256,
        })
        store._checkpoint(
            intent.task_id,
            "TARGET_EFFECT_COMMITTED",
            "PASS",
            "VERIFIED_COMPLETE",
            {"readback_sha256": evidence.readback_sha256, "verifier_ref": evidence.verifier_ref},
        )

    return evidence
