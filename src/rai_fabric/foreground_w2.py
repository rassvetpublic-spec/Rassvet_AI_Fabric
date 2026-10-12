"""W2/10.5: ограниченный foreground-worker только для синтетических эффектов.

Без службы, произвольных команд, реальных провайдеров и автоматического replay.
SQLite Effect Ledger коммитится ДО вызова собственного Windows Job.
"""
from __future__ import annotations

__version__ = "0.1.0"

import sys
import time
import uuid
from pathlib import Path

from .effect_ledger import EffectLedger, SyntheticSQLiteTarget, _identifier, _sha
from .store import FabricError, FabricStore
from .windows_owned_job import run_synthetic_job

_CASES = frozenset({"EXIT_ZERO", "EXIT_NONZERO", "HANG_PARENT", "SPAWN_DESCENDANT"})


def _summary(store: FabricStore, ledger: EffectLedger, task_id: str,
             target_id: str, operation_id: str, reason: str) -> dict:
    """Публичный результат без аренды, исходного payload, путей и PID."""
    state = store.get(task_id)
    effects = ledger.list_for_task(task_id)
    phase = next((e["phase"] for e in effects
                  if e["target_id"] == target_id and e["operation_id"] == operation_id), "NONE")
    return {"task_id": task_id, "status": state["status"], "effect_phase": phase,
            "receipt_count": len(ledger.receipts_for_task(task_id)),
            "reason_code": reason, "synthetic": True, "external_provider_calls": 0}


def _settle_blocked(store: FabricStore, ledger: EffectLedger, task_id: str,
                    owner: str, lease_token: str, reason: str) -> None:
    """Только fail-closed завершение; если lease потерян, потребуется recovery."""
    state = store.get(task_id)
    if state["status"] == "RUNNING":
        try:
            if state["cancel_requested"]:
                store.confirm_cancel(task_id, owner, lease_token)
            else:
                store.finish(task_id, owner, lease_token, verdict="BLOCKED",
                             response=reason,
                             evidence={"synthetic": True, "external_provider_calls": 0,
                                       "failure_code": reason},
                             cursor="VERIFY_SYNTHETIC_EFFECT_BEFORE_NEW_INTENT")
        except FabricError:
            # Expired lease: recover() may settle it. Never force a terminal state.
            store.recover()
    ledger.recover_pending_effects()
    if store.get(task_id)["status"] not in ("BLOCKED", "CANCELLED"):
        raise FabricError("W2_FOREGROUND_TERMINAL_STATE_UNVERIFIED")


def run_foreground_synthetic_once(store: FabricStore, target: SyntheticSQLiteTarget, *,
                                  operation_id: str, payload_sha256: str,
                                  case: str = "EXIT_ZERO", timeout_seconds: float = 3.0,
                                  task_id: str | None = None,
                                  owner: str | None = None) -> dict:
    """Одна synthetic mock-задача с fenced PREPARED→MAY_HAVE_RUN→receipt.

    На timeout/cancel/error неизвестный эффект нельзя повторно поставить в очередь.
    Доступен только на Windows; пользовательские программы НЕ принимаются.
    """
    # All argument and authority checks must happen before claim/spawn.
    if sys.platform != "win32":
        raise FabricError("W2_FOREGROUND_WINDOWS_ONLY")
    if type(store) is not FabricStore or type(target) is not SyntheticSQLiteTarget:
        raise FabricError("W2_FOREGROUND_SYNTHETIC_STORE_AND_TARGET_ONLY")
    if store.path == target.path:
        raise FabricError("W2_FOREGROUND_TARGET_MUST_BE_INDEPENDENT")
    if case not in _CASES:
        raise FabricError("W2_FOREGROUND_CASE_NOT_ALLOWED")
    if type(timeout_seconds) not in (int, float) or not 0.1 <= timeout_seconds <= 30.0:
        raise FabricError("W2_FOREGROUND_TIMEOUT_INVALID")
    if task_id is not None and (type(task_id) is not str or not task_id):
        raise FabricError("W2_FOREGROUND_TASK_ID_INVALID")
    op_id = _identifier(operation_id)
    digest = _sha(payload_sha256)
    ledger = EffectLedger(store)  # explicit schema v2; never migrates a legacy DB
    task_owner = owner if owner is not None else "w2-fg-" + uuid.uuid4().hex[:12]
    if not isinstance(task_owner, str) or not 1 <= len(task_owner) <= 120:
        raise FabricError("W2_FOREGROUND_OWNER_INVALID")
    claimed = store.claim(task_owner, provider="mock", task_id=task_id,
                          lease_seconds=120)
    if claimed is None:
        return {"status": "NO_READY_TASK", "synthetic": True, "external_provider_calls": 0}
    identity = claimed["task_id"]
    token = claimed["lease_token"]
    target_id = target.target_id
    reason = "W2_FOREGROUND_UNEXPECTED_FAILURE"
    try:
        ledger.prepare_effect(identity, task_owner, token,
                              target_id=target_id, operation_id=op_id,
                              payload_sha256=digest, expected_revision="rev-0")
        # Crash after this commit MUST recover as UNKNOWN_OUTCOME.
        ledger.mark_possible_dispatch(identity, task_owner, token,
                                      target_id=target_id, operation_id=op_id)

        def cancellation_or_fence_lost() -> bool:
            current = store.get(identity)
            if (current["status"] != "RUNNING" or
                    current["lease_owner"] != task_owner or
                    current["lease_epoch"] != claimed["lease_epoch"] or
                    current["lease_deadline"] is None or
                    current["lease_deadline"] <= time.time()):
                raise FabricError("W2_FOREGROUND_LEASE_FENCE_LOST")
            return bool(current["cancel_requested"])

        if cancellation_or_fence_lost():
            store.confirm_cancel(identity, task_owner, token)
            ledger.recover_pending_effects()
            return _summary(store, ledger, identity, target_id, op_id, "CANCELLED_BEFORE_SPAWN")

        # Never pass external binaries/commands; owned Job fixture IDs only.
        outcome = run_synthetic_job(case, timeout_seconds=timeout_seconds,
                                    cwd=Path(claimed["workspace"]),
                                    cancel_check=cancellation_or_fence_lost)
        if outcome["verdict"] == "OWNED_GROUP_CANCELLED":
            if not store.get(identity)["cancel_requested"]:
                raise FabricError("W2_FOREGROUND_CANCEL_UNVERIFIED")
            store.confirm_cancel(identity, task_owner, token)
            ledger.recover_pending_effects()
            return _summary(store, ledger, identity, target_id, op_id, "OWNED_JOB_CANCELLED")
        if outcome["verdict"] != "EXITED" or outcome.get("exit_code") != 0:
            reason = "OWNED_JOB_NO_SUCCESS_OR_TIMEOUT"
            _settle_blocked(store, ledger, identity, task_owner, token, reason)
            return _summary(store, ledger, identity, target_id, op_id, reason)
        if (outcome.get("descendants_active") != 0 or
                outcome.get("owned_job") is not True or
                outcome.get("external_provider_calls") != 0):
            raise FabricError("W2_FOREGROUND_OWNED_JOB_EVIDENCE_INVALID")

        # Revalidate active lease and cancellation before synthetic target write.
        if cancellation_or_fence_lost():
            store.confirm_cancel(identity, task_owner, token)
            ledger.recover_pending_effects()
            return _summary(store, ledger, identity, target_id, op_id, "CANCELLED_BEFORE_TARGET")
        store.heartbeat(identity, task_owner, token, lease_seconds=120)
        target.apply(op_id, digest)  # independent *synthetic* SQLite, NOT a provider
        reconciled = ledger.reconcile_synthetic(target, op_id)
        if reconciled["phase"] != "APPLIED_VERIFIED":
            raise FabricError("W2_FOREGROUND_TARGET_RECEIPT_NOT_VERIFIED")
        if cancellation_or_fence_lost():
            store.confirm_cancel(identity, task_owner, token)
            return _summary(store, ledger, identity, target_id, op_id, "CANCELLED_AFTER_EFFECT")
        store.finish(identity, task_owner, token, verdict="PASS",
                     response="W2 synthetic target receipt verified",
                     evidence={"synthetic": True, "external_provider_calls": 0,
                               "owned_job": True, "receipt_verified": True},
                     cursor="REVIEW_SYNTHETIC_RECEIPT")
        return _summary(store, ledger, identity, target_id, op_id, "SYNTHETIC_RECEIPT_VERIFIED")
    except Exception:
        # Never log exception messages or tokens from an external failure.
        _settle_blocked(store, ledger, identity, task_owner, token, reason)
        return _summary(store, ledger, identity, target_id, op_id, reason)


def recover_foreground_synthetic(store: FabricStore) -> dict:
    """Без replay: истёкшие аренды → BLOCKED и UNKNOWN_OUTCOME."""
    if type(store) is not FabricStore:
        raise FabricError("W2_FOREGROUND_STORE_INVALID")
    ledger = EffectLedger(store)
    blocked = store.recover()
    unknown = ledger.recover_pending_effects()
    return {"blocked_task_ids": blocked, "unknown_effect_count": len(unknown),
            "replayed": 0, "external_provider_calls": 0, "synthetic": True}
