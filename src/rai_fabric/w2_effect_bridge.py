"""W2 Effect Bridge: безопасное проведение реальных эффектов через доверенный верификатор.

Инварианты:
1. Replay/дубликат операции категорически отклоняется.
2. Stale epoch (несовпадающая эпоха аренды) отклоняется.
3. Прямой finish(PASS) без проверенной квитанции заблокирован.
4. Откат при ошибке сохраняет статус QUEUED без утечек.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
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
    if getattr(grant_registry, "is_default_key", False) and intent.provider not in ("mock", "codex-mock"):
        raise ReceiptRejected("DEFAULT_SIGNING_KEY_FORBIDDEN: Real provider intents require injected owner authority")

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
    grant_registry: LocalTrustedGrantRegistry,
    *,
    owner: str = "antigravity",
    lease_token: str | None = None,
) -> dict[str, Any]:
    """Авторизованный W2 lease gate: перевод задачи реального провайдера в статус RUNNING."""
    if grant_registry is None or not isinstance(grant_registry, LocalTrustedGrantRegistry):
        raise FabricError("MANDATORY_GRANT_REGISTRY_REQUIRED: Real provider tasks require an authenticated LocalTrustedGrantRegistry")

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

        # Строгая сверка всех полей зарегистрированного намерения против caller intent
        if (
            intent_row["task_id"] != intent.task_id
            or intent_row["provider"] != intent.provider
            or intent_row["target_id"] != intent.target_id
            or intent_row["host_id"] != intent.host_id
            or intent_row["operation_id"] != intent.operation_id
            or intent_row["envelope_id"] != intent.envelope_id
            or intent_row["lease_epoch"] != intent.lease_epoch
            or intent_row["lease_deadline_utc"] != intent.lease_deadline_utc
            or intent_row["payload_sha256"] != intent.payload_sha256
            or intent_row["owner_grant_ref"] != intent.owner_grant_ref
        ):
            raise FabricError("PERSISTED_INTENT_MISMATCH")

        # Обязательная проверка мандата владельца при получении лизы
        if not grant_registry.authorize(intent):
            raise FabricError("UNAUTHORIZED_CLAIM: Owner grant verification failed")
        if getattr(grant_registry, "is_default_key", False) and intent.provider not in ("mock", "codex-mock"):
            raise FabricError("DEFAULT_SIGNING_KEY_FORBIDDEN: Real provider lease requires injected owner authority")

        now = time.time()
        if intent.lease_deadline_utc <= now:
            raise FabricError("LEASE_DEADLINE_EXPIRED")

        token = lease_token if lease_token is not None else secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        cursor = store.db.execute("""
            UPDATE tasks
            SET status='RUNNING', lease_owner=?, lease_hash=?, lease_epoch=?,
                lease_deadline=?, attempt=attempt+1, updated_at=?
            WHERE id=? AND status='QUEUED' AND cancel_requested=0
        """, (owner, digest, intent.lease_epoch, intent.lease_deadline_utc, now, intent.task_id))
        if cursor.rowcount != 1:
            raise FabricError("CLAIM_CAS_FAILED")

        store._event(intent.task_id, "CLAIMED_REAL_TASK", {"owner": owner, "epoch": intent.lease_epoch})
        store._checkpoint(intent.task_id, "DISPATCHED_REAL_TASK", "PARTIAL", "EXECUTE",
                          {"owner": owner, "epoch": intent.lease_epoch})
        return {
            "task_id": intent.task_id,
            "lease_token": token,
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
    lease_token: str | None = None,
    lease_owner: str = "antigravity",
) -> AdmissibleEvidence:
    """Атомарная валидация и коммит эффекта в W2 FabricStore через авторизованный шлюз владельца."""
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

        # Обязательное наличие и проверка lease_owner
        stored_lease_owner = task_row["lease_owner"]
        if not stored_lease_owner or not isinstance(stored_lease_owner, str):
            raise ReceiptRejected("TASK_UNLEASED")
        if lease_owner is not None and stored_lease_owner != lease_owner:
            raise ReceiptRejected("LEASE_OWNER_MISMATCH")

        if task_row["lease_deadline"] is not None and task_row["lease_deadline"] < now_utc:
            raise ReceiptRejected("LEASE_EXPIRED")

        # Безусловное требование валидного 64-hex lease_hash (P0-B: никаких обходов при NULL/пустом хэше)
        stored_lease_hash = task_row["lease_hash"]
        if (
            not stored_lease_hash
            or not isinstance(stored_lease_hash, str)
            or len(stored_lease_hash) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in stored_lease_hash)
        ):
            raise ReceiptRejected("MISSING_OR_INVALID_LEASE_HASH")

        # Валидация криптографического токена аренды против task_row["lease_hash"]
        if not lease_token or not isinstance(lease_token, str):
            raise ReceiptRejected("MISSING_LEASE_TOKEN")
        token_digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(stored_lease_hash.lower(), token_digest.lower()):
            raise ReceiptRejected("LEASE_TOKEN_MISMATCH")

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

        # Проверка скоупа мандата владельца (P0-C: ALLOWED_MANDATE_SCOPES allowlist & fail-closed)
        from .trusted_target_verifier import ALLOWED_MANDATE_SCOPES
        grant = grant_registry.get_grant(intent.owner_grant_ref) if hasattr(grant_registry, "get_grant") else None
        if not grant:
            raise ReceiptRejected("OWNER_GRANT_NOT_FOUND")
        mandate_scope = getattr(grant, "mandate_scope", None)
        if mandate_scope not in ALLOWED_MANDATE_SCOPES:
            raise ReceiptRejected(f"UNKNOWN_MANDATE_SCOPE: {mandate_scope}")

        if mandate_scope == "EVIDENCE_ADMISSIBLE_ONLY":
            # Фиксируем квитанцию, но НЕ переводим задачу в COMPLETE/PASS
            store._event(intent.task_id, "EFFECT_EVIDENCE_RECORDED", {
                "operation_id": intent.operation_id,
                "verifier_ref": evidence.verifier_ref,
                "readback_sha256": evidence.readback_sha256,
            })
            store._checkpoint(
                intent.task_id,
                "TARGET_EFFECT_ADMISSIBLE",
                "PARTIAL",
                "EVIDENCE_HELD",
                {"readback_sha256": evidence.readback_sha256, "verifier_ref": evidence.verifier_ref},
            )
            return evidence
        elif mandate_scope == "OWNER_AUTHORIZED_FINAL_PASS":
            # Переводим задачу в COMPLETE с признаком PASS через единый строго защищённый CAS:
            # WHERE id=? AND status='RUNNING' AND lease_epoch=? AND lease_owner=? AND lease_hash=? AND cancel_requested=0
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
                WHERE id=?
                  AND status='RUNNING'
                  AND lease_epoch=?
                  AND lease_owner=?
                  AND lease_hash=?
                  AND cancel_requested=0
            """, (
                result_payload,
                now_utc,
                intent.task_id,
                receipt.lease_epoch,
                stored_lease_owner,
                stored_lease_hash,
            ))
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
        else:
            raise ReceiptRejected(f"UNAUTHORIZED_MANDATE_SCOPE: {mandate_scope}")

    return evidence
