"""W2 *shadow-only* receipt/lease candidate; never completes real tasks.

Admissible source evidence is NOT an authenticated external effect, a host
capability, or permission for FabricStore.finish(PASS). The only supported
state change is optional staging of a QUEUED task/intent in a disposable DB.
The production real-provider claim/finish gate in FabricStore remains closed.
"""
from __future__ import annotations

import hashlib
import hmac
import math
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
from .store import FabricStore
from .trusted_target_verifier import LocalTrustedGrantRegistry, LocalTargetReadbackVerifier


_INTENT_FIELDS = (
    "task_id", "provider", "target_id", "host_id", "operation_id",
    "envelope_id", "lease_epoch", "lease_deadline_utc", "payload_sha256",
    "owner_grant_ref",
)
_OPERATION_FIELDS = ("task_id", "target_id", "operation_id", "payload_sha256", "lease_epoch")


def register_real_intent(
    store: FabricStore,
    intent: EffectIntent,
    grant_registry: LocalTrustedGrantRegistry,
    workspace: str | Path | None = None,
    *,
    shadow_only: bool = False,
) -> dict[str, Any]:
    """Stage a real-provider *intent* in test DB only; never claim or execute."""
    if not shadow_only:
        raise ReceiptRejected("REAL_INTENT_SHADOW_ONLY")
    if not isinstance(store, FabricStore) or not isinstance(intent, EffectIntent):
        raise ReceiptRejected("INVALID_INTENT_TYPE")
    if not isinstance(grant_registry, LocalTrustedGrantRegistry) or not grant_registry.authorize(intent):
        raise ReceiptRejected("OWNER_GRANT_DENIED")
    if intent.provider not in ("antigravity", "codex-app"):
        raise ReceiptRejected("NOT_REAL_PROVIDER")
    if type(intent.lease_epoch) is not int or intent.lease_epoch <= 0:
        raise ReceiptRejected("INVALID_INTENT_EPOCH")
    if not isinstance(intent.lease_deadline_utc, (int, float)) or not math.isfinite(intent.lease_deadline_utc):
        raise ReceiptRejected("INVALID_INTENT_DEADLINE")

    ws = str(Path(workspace).resolve()) if workspace else str(Path.cwd().resolve())
    with store.atomic():
        task = store.submit(
            objective=f"Shadow real intent {intent.operation_id} on {intent.target_id}",
            provider=intent.provider, workspace=ws, task_id=intent.task_id,
        )
        if task.get("status") != "QUEUED":
            raise ReceiptRejected("SHADOW_INTENT_TASK_NOT_QUEUED")
        now = time.time()
        store.db.execute("""
            INSERT INTO effect_intents (
                task_id, provider, target_id, host_id, operation_id, envelope_id,
                lease_epoch, lease_deadline_utc, payload_sha256, owner_grant_ref, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            intent.task_id, intent.provider, intent.target_id, intent.host_id,
            intent.operation_id, intent.envelope_id, intent.lease_epoch,
            intent.lease_deadline_utc, intent.payload_sha256, intent.owner_grant_ref, now,
        ))
        store.db.execute("""
            INSERT INTO effect_operations (
                task_id, target_id, operation_id, payload_sha256, lease_epoch,
                expected_revision, phase, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?)
        """, (
            intent.task_id, intent.target_id, intent.operation_id,
            intent.payload_sha256, intent.lease_epoch, "unverified", now, now,
        ))
        return task


def _bound_intent_and_operation(store: FabricStore, intent: EffectIntent) -> None:
    """Reject replay, partial intent, or tampered persisted effect records."""
    row = store.db.execute(
        "SELECT * FROM effect_intents WHERE task_id=?", (intent.task_id,)
    ).fetchone()
    if row is None:
        raise ReceiptRejected("PERSISTED_INTENT_MISSING")
    for field in _INTENT_FIELDS:
        stored, supplied = row[field], getattr(intent, field)
        if stored != supplied or type(stored) is not type(supplied):
            # SQLite INTEGER/REAL may convert Python integers to float:
            # types must agree after known intentional REAL coercion only.
            if field != "lease_deadline_utc" or stored != float(supplied):
                raise ReceiptRejected("PERSISTED_INTENT_MISMATCH_" + field.upper())
    operation = store.db.execute(
        "SELECT * FROM effect_operations WHERE target_id=? AND operation_id=?",
        (intent.target_id, intent.operation_id),
    ).fetchone()
    if operation is None:
        raise ReceiptRejected("PERSISTED_OPERATION_MISSING")
    for field in _OPERATION_FIELDS:
        if operation[field] != getattr(intent, field):
            raise ReceiptRejected("PERSISTED_OPERATION_MISMATCH_" + field.upper())
    if operation["phase"] != "PREPARED":
        raise ReceiptRejected("EFFECT_NOT_PREPARED_OR_POSSIBLY_ALREADY_RUN")
    if store.db.execute(
        "SELECT 1 FROM effect_receipts WHERE target_id=? AND operation_id=?",
        (intent.target_id, intent.operation_id),
    ).fetchone():
        raise ReceiptRejected("DUPLICATE_EFFECT_REPLAY")


def commit_verified_effect_receipt(
    store: FabricStore,
    intent: EffectIntent,
    receipt: TargetEffectReceipt,
    *,
    now_utc: float,
    grant_registry: LocalTrustedGrantRegistry,
    target_verifier: LocalTargetReadbackVerifier,
    lease_owner: str | None = None,
    lease_token: str | None = None,
) -> AdmissibleEvidence:
    """Review a proposed commit and DENY real-provider completion unconditionally.

    Every state/lease check is exercised for defensive regression, but there is
    no trusted host execution signer or independently proven effect capability.
    A future separately approved integration may implement a different, gated
    transaction. NEVER change this function to PASS from AdmissibleEvidence.
    """
    if not isinstance(store, FabricStore):
        raise ReceiptRejected("INVALID_FABRIC_STORE")
    if not isinstance(grant_registry, LocalTrustedGrantRegistry):
        raise ReceiptRejected("INVALID_GRANT_VERIFIER")
    if not isinstance(target_verifier, LocalTargetReadbackVerifier):
        raise ReceiptRejected("INVALID_TARGET_VERIFIER")
    # Pure correlation/readback admission, NOT a grant to change task status.
    evidence = verify_effect_receipt(
        intent, receipt, now_utc=now_utc,
        authorize_grant=grant_registry.authorize,
        verify_target=target_verifier.verify_target,
    )
    if evidence.classification != "EVIDENCE_ADMISSIBLE_NOT_QA_PASS":
        raise ReceiptRejected("UNEXPECTED_EVIDENCE_CLASSIFICATION")
    with store.atomic():
        _bound_intent_and_operation(store, intent)
        task = store.db.execute("SELECT * FROM tasks WHERE id=?", (intent.task_id,)).fetchone()
        if task is None:
            raise ReceiptRejected("TASK_NOT_FOUND")
        if task["provider"] != intent.provider:
            raise ReceiptRejected("TASK_PROVIDER_MISMATCH")
        if task["cancel_requested"] != 0 or task["status"] == "CANCELLED":
            raise ReceiptRejected("CANCELLED_EFFECT_DENIED")
        if task["status"] != "RUNNING":
            raise ReceiptRejected("ACTIVE_RUNNING_LEASE_REQUIRED")
        if task["lease_epoch"] != intent.lease_epoch or task["lease_epoch"] != receipt.lease_epoch:
            raise ReceiptRejected("STALE_LEASE_EPOCH")
        if (not isinstance(now_utc, (int, float)) or not math.isfinite(now_utc)
                or task["lease_deadline"] is None or task["lease_deadline"] <= now_utc):
            raise ReceiptRejected("LEASE_EXPIRED")
        if not isinstance(lease_owner, str) or not isinstance(lease_token, str) or not lease_token:
            raise ReceiptRejected("LEASE_PROOF_MISSING")
        if task["lease_owner"] != lease_owner or not task["lease_hash"]:
            raise ReceiptRejected("LEASE_OWNER_MISMATCH")
        digest = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(task["lease_hash"], digest):
            raise ReceiptRejected("LEASE_TOKEN_INVALID")
        # EVEN A VALID LEASE IS NOT PROOF OF TARGET EFFECT OR ISSUER AUTHORITY.
        # No UPDATE of tasks/effect_operations/effect_receipts. No PASS checkpoint.
        raise ReceiptRejected("HOST_EFFECT_AUTHORITY_NOT_IMPLEMENTED")
