"""Offline negative and positive contract tests: no transport, host or task writes."""
from dataclasses import replace
import pytest

from rai_fabric.effect_receipt_contract import (
    EffectIntent, TargetEffectReceipt, VerifiedReadback,
    ReceiptRejected, verify_effect_receipt,
)

DIGEST = "a" * 64
OUTPUT = "b" * 64
NOW = 1_800_000_100.0


def fixture():
    intent = EffectIntent(
        task_id="job-001", provider="antigravity", target_id="approved-project",
        host_id="RASSVET_DESKTOP", operation_id="op-01", envelope_id="env-01",
        lease_epoch=2, lease_deadline_utc=NOW + 30, payload_sha256=DIGEST,
        owner_grant_ref="owner-mtd-scoped-01",
    )
    receipt = TargetEffectReceipt(
        task_id=intent.task_id, provider=intent.provider, target_id=intent.target_id,
        host_id=intent.host_id, operation_id=intent.operation_id,
        envelope_id=intent.envelope_id, lease_epoch=intent.lease_epoch,
        verdict="APPLIED_VERIFIED", applied_sha256=DIGEST,
        target_revision="rev-02", readback_sha256=OUTPUT,
        attestation_ref="external-target-attestation-ref", observed_at_utc=NOW - 1,
    )
    def grant(_):
        return True
    def verified(_, __):
        return VerifiedReadback(
            target_id=intent.target_id, host_id=intent.host_id,
            target_revision=receipt.target_revision,
            content_sha256=receipt.readback_sha256, verifier_ref="trusted-independent-verifier",
        )
    return intent, receipt, grant, verified


def accept(intent=None, receipt=None, grant=None, verified=None, now=NOW):
    i, r, g, v = fixture()
    return verify_effect_receipt(
        i if intent is None else intent,
        r if receipt is None else receipt,
        now_utc=now,
        authorize_grant=g if grant is None else grant,
        verify_target=v if verified is None else verified,
    )


def test_evidence_never_implicitly_returns_pass():
    assert accept().classification == "EVIDENCE_ADMISSIBLE_NOT_QA_PASS"


@pytest.mark.parametrize("field,wrong", [
    ("task_id", "other-task"), ("provider", "codex-app"),
    ("target_id", "other-target"), ("host_id", "other-host"),
    ("operation_id", "other-op"), ("envelope_id", "other-env"),
    ("lease_epoch", 3),
])
def test_pinned_correlation_is_required(field, wrong):
    i, r, g, v = fixture()
    with pytest.raises(ReceiptRejected, match="CORRELATION_MISMATCH"):
        accept(intent=i, receipt=replace(r, **{field: wrong}), grant=g, verified=v)


@pytest.mark.parametrize("status", ["ACK", "QUEUED", "SUCCESS", "BLOCKED", "UNKNOWN"])
def test_transport_or_self_report_never_accepted(status):
    i, r, g, v = fixture()
    with pytest.raises(ReceiptRejected, match="NOT_TARGET_VERIFIED"):
        accept(receipt=replace(r, verdict=status))


def test_missing_verifiers_fail_closed():
    i, r, g, v = fixture()
    with pytest.raises(ReceiptRejected, match="TRUST_VERIFIERS_ABSENT"):
        verify_effect_receipt(i, r, now_utc=NOW, authorize_grant=None, verify_target=None)


def test_authority_must_return_exact_true():
    with pytest.raises(ReceiptRejected, match="OWNER_GRANT_NOT_VERIFIED"):
        accept(grant=lambda _: "ACK")


def test_expired_lease_never_accepted():
    with pytest.raises(ReceiptRejected, match="STALE_OR_FUTURE_EFFECT"):
        accept(now=NOW + 40)


def test_future_receipt_never_accepted():
    i, r, g, v = fixture()
    with pytest.raises(ReceiptRejected, match="STALE_OR_FUTURE_EFFECT"):
        accept(receipt=replace(r, observed_at_utc=NOW + 1))


def test_payload_digest_must_match_intent():
    i, r, g, v = fixture()
    with pytest.raises(ReceiptRejected, match="PAYLOAD_DIGEST_MISMATCH"):
        accept(receipt=replace(r, applied_sha256="c" * 64))


def test_unverified_target_readback_is_rejected():
    with pytest.raises(ReceiptRejected, match="TRUSTED_READBACK_ABSENT"):
        accept(verified=lambda *_: None)


def test_readback_mismatch_is_rejected():
    i, r, g, v = fixture()
    with pytest.raises(ReceiptRejected, match="TARGET_READBACK_MISMATCH"):
        accept(verified=lambda *_: replace(v(i, r), content_sha256="c" * 64))


def test_mock_cannot_be_promoted_as_real_receipt():
    i, r, g, v = fixture()
    with pytest.raises(ReceiptRejected, match="NOT_REAL_PROVIDER"):
        accept(intent=replace(i, provider="mock"))


def test_invalid_digest_and_epoch_are_rejected():
    i, r, g, v = fixture()
    with pytest.raises(ReceiptRejected, match="INVALID_INTENT_DIGEST"):
        accept(intent=replace(i, payload_sha256="abc"))
    with pytest.raises(ReceiptRejected, match="INVALID_LEASE_EPOCH"):
        accept(intent=replace(i, lease_epoch=0), receipt=replace(r, lease_epoch=0))


def test_target_verifier_failure_fails_closed():
    def raise_it(*_):
        raise RuntimeError("no trusted target")
    with pytest.raises(ReceiptRejected, match="TARGET_READBACK_FAILED"):
        accept(verified=raise_it)


@pytest.mark.parametrize("invalid_epoch", [True, 2.0])
def test_receipt_epoch_requires_exact_integer_type(invalid_epoch):
    i, r, g, v = fixture()
    with pytest.raises(ReceiptRejected, match="INVALID_LEASE_EPOCH"):
        accept(intent=i, receipt=replace(r, lease_epoch=invalid_epoch))
