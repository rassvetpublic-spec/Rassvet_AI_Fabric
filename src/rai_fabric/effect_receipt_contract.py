"""Offline real-provider receipt admission contract. NOT WIRED TO EXECUTION.

The host/authority checkers must be supplied by a separately approved integration.
A TransportMessageEnvelope SHA256 digest is *not* an authenticated target proof.
This module never claims, executes, finishes, writes or starts a process.
"""
from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from typing import Callable


class ReceiptRejected(ValueError):
    """An effect receipt is not admissible as verified target evidence."""


@dataclass(frozen=True)
class EffectIntent:
    task_id: str
    provider: str
    target_id: str
    host_id: str
    operation_id: str
    envelope_id: str
    lease_epoch: int
    lease_deadline_utc: float
    payload_sha256: str
    owner_grant_ref: str


@dataclass(frozen=True)
class TargetEffectReceipt:
    task_id: str
    provider: str
    target_id: str
    host_id: str
    operation_id: str
    envelope_id: str
    lease_epoch: int
    verdict: str
    applied_sha256: str
    target_revision: str
    readback_sha256: str
    attestation_ref: str
    observed_at_utc: float


@dataclass(frozen=True)
class VerifiedReadback:
    target_id: str
    host_id: str
    target_revision: str
    content_sha256: str
    verifier_ref: str


@dataclass(frozen=True)
class AdmissibleEvidence:
    """Validated input to a FUTURE owner-approved commit gate; never a PASS."""
    classification: str
    task_id: str
    operation_id: str
    target_id: str
    host_id: str
    lease_epoch: int
    verifier_ref: str
    readback_sha256: str


def _hash(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _filled(value: str) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 256 and value.strip() == value


def verify_effect_receipt(
    intent: EffectIntent,
    receipt: TargetEffectReceipt,
    *,
    now_utc: float,
    authorize_grant: Callable[[EffectIntent], bool] | None,
    verify_target: Callable[[EffectIntent, TargetEffectReceipt], VerifiedReadback | None] | None,
) -> AdmissibleEvidence:
    """Fail-closed, pure correlation gate; callbacks own real trust and readback.

    The caller must inject trusted verifiers, which are NOT implemented here.
    Returning AdmissibleEvidence does not permit FabricStore.finish(PASS).
    """
    if not isinstance(intent, EffectIntent) or not isinstance(receipt, TargetEffectReceipt):
        raise ReceiptRejected("INVALID_TYPED_RECEIPT")
    if not callable(authorize_grant) or not callable(verify_target):
        raise ReceiptRejected("TRUST_VERIFIERS_ABSENT")
    if intent.provider not in {"antigravity", "codex-app"}:
        raise ReceiptRejected("NOT_REAL_PROVIDER")
    if not all(_filled(v) for v in (
        intent.task_id, intent.target_id, intent.host_id, intent.operation_id,
        intent.envelope_id, intent.owner_grant_ref,
    )):
        raise ReceiptRejected("MISSING_PINNED_IDENTITY")
    if not _hash(intent.payload_sha256):
        raise ReceiptRejected("INVALID_INTENT_DIGEST")
    if type(intent.lease_epoch) is not int or intent.lease_epoch <= 0:
        raise ReceiptRejected("INVALID_LEASE_EPOCH")
    if not all(isinstance(t, (float, int)) and math.isfinite(t)
               for t in (now_utc, intent.lease_deadline_utc, receipt.observed_at_utc)):
        raise ReceiptRejected("INVALID_CLOCK")
    if not (0 < receipt.observed_at_utc <= now_utc < intent.lease_deadline_utc):
        raise ReceiptRejected("STALE_OR_FUTURE_EFFECT")
    for key in ("task_id", "provider", "target_id", "host_id", "operation_id", "envelope_id", "lease_epoch"):
        if getattr(intent, key) != getattr(receipt, key):
            raise ReceiptRejected("CORRELATION_MISMATCH_" + key.upper())
    if receipt.verdict != "APPLIED_VERIFIED":
        raise ReceiptRejected("NOT_TARGET_VERIFIED")
    if not all(_filled(v) for v in (receipt.target_revision, receipt.attestation_ref)):
        raise ReceiptRejected("MISSING_TARGET_PROOF")
    if not _hash(receipt.applied_sha256) or not _hash(receipt.readback_sha256):
        raise ReceiptRejected("INVALID_EFFECT_DIGEST")
    if not hmac.compare_digest(receipt.applied_sha256, intent.payload_sha256):
        raise ReceiptRejected("PAYLOAD_DIGEST_MISMATCH")
    try:
        grant_ok = authorize_grant(intent)
    except Exception as exc:
        raise ReceiptRejected("GRANT_VERIFICATION_FAILED") from exc
    if grant_ok is not True:
        raise ReceiptRejected("OWNER_GRANT_NOT_VERIFIED")
    try:
        verified = verify_target(intent, receipt)
    except Exception as exc:
        raise ReceiptRejected("TARGET_READBACK_FAILED") from exc
    if not isinstance(verified, VerifiedReadback) or not _filled(verified.verifier_ref):
        raise ReceiptRejected("TRUSTED_READBACK_ABSENT")
    if (verified.target_id != intent.target_id or verified.host_id != intent.host_id
            or verified.target_revision != receipt.target_revision
            or not _hash(verified.content_sha256)
            or not hmac.compare_digest(verified.content_sha256, receipt.readback_sha256)):
        raise ReceiptRejected("TARGET_READBACK_MISMATCH")
    return AdmissibleEvidence(
        classification="EVIDENCE_ADMISSIBLE_NOT_QA_PASS",
        task_id=intent.task_id, operation_id=intent.operation_id,
        target_id=intent.target_id, host_id=intent.host_id,
        lease_epoch=intent.lease_epoch, verifier_ref=verified.verifier_ref,
        readback_sha256=verified.content_sha256,
    )