"""CP-54B3: bounded, opt-in, local-only active-session evidence observer.

This is NOT proof of Google account identity or a binding to a RAiF vault ID.
It deliberately never serializes email, user fields, tokens or raw replies.
The private LS RPC is not a stable public provider API. A live read may cause
provider traffic inside the LS, so it requires a separate explicit runtime gate.
"""
from __future__ import annotations

from typing import Callable

from .native_rpc import (
    LocalRpcTarget, NativeRpcError, _post_fixed_local_rpc,
)

_MAX_STATUS_BYTES = 256 * 1024
_SAFE_RPC_CODES = frozenset({
    "RPC_HTTP_NON_200", "RPC_RESPONSE_SIZE_INVALID", "RPC_RESPONSE_LENGTH_INVALID",
    "RPC_RESPONSE_JSON_INVALID", "RPC_RESPONSE_SCHEMA_INVALID",
    "RPC_TRANSPORT_FAILED", "RPC_TIMEOUT_INVALID",
})


def _verdict(code: str, *, status: bool | None = None,
             plan: bool | None = None) -> dict:
    """Fixed-schema report. No user-controlled strings or opaque IDs escape."""
    return {
        "verdict": code,
        "source": "NATIVE_HTTPS_CONNECT_RPC",
        "observation_scope": "ONE_LS_UNATTRIBUTED",
        "user_status_present": status,
        "plan_info_present": plan,
        "account_identity_verified": False,
        "matched_account_id": None,
        "provider_access_verified": False,
        "eligible_for_pool": False,
        "hot_swap_verified": False,
        "stream_continuity_verified": False,
    }


def summarize_active_identity(payload: object) -> dict:
    """Only schema-presence booleans; deliberately does not extract email.

    Neither plan name nor `hasValidAuth` is an independent identity claim.
    A future attested local comparator requires a separate design and gate.
    """
    if not isinstance(payload, dict):
        return _verdict("IDENTITY_SCHEMA_UNSUPPORTED")
    if "response" in payload:
        body = payload["response"]
    else:
        body = payload
    if not isinstance(body, dict):
        return _verdict("IDENTITY_SCHEMA_UNSUPPORTED")
    if ("userStatus" in body and "user_status" in body) or (
        "planInfo" in body and "plan_info" in body
    ):
        return _verdict("IDENTITY_SCHEMA_AMBIGUOUS")
    user_status = body.get("userStatus", body.get("user_status"))
    plan = body.get("planInfo", body.get("plan_info"))
    if user_status is not None and not isinstance(user_status, dict):
        return _verdict("IDENTITY_SCHEMA_UNSUPPORTED")
    if plan is not None and not isinstance(plan, dict):
        return _verdict("IDENTITY_SCHEMA_UNSUPPORTED")
    present = isinstance(user_status, dict)
    plan_present = isinstance(plan, dict)
    return _verdict(
        "IDENTITY_UNVERIFIED" if present else "USER_STATUS_NOT_PRESENT",
        status=present, plan=plan_present,
    )


def collect_active_identity(
    target: LocalRpcTarget, *, allow_identity_read: bool = False,
    ownership_verified: Callable[[], bool] | None = None,
    sender: Callable[[LocalRpcTarget], dict] | None = None,
) -> dict:
    """One opt-in GetUserStatus on a verified live loopback LS; no discovery.

    The trusted host must verify PID, process-creation marker, Antigravity parent,
    and own localhost listener just before calling. No credentials are read.
    `sender` exists only for offline synthetic tests and must never log payloads.
    """
    if allow_identity_read is not True:
        return _verdict("IDENTITY_OPT_IN_REQUIRED")
    if not isinstance(target, LocalRpcTarget):
        return _verdict("IDENTITY_TARGET_INVALID")
    if not callable(ownership_verified):
        return _verdict("RPC_OWNER_EVIDENCE_REQUIRED")
    try:
        if ownership_verified() is not True:
            return _verdict("RPC_OWNER_EVIDENCE_FAILED")
    except Exception:
        return _verdict("RPC_OWNER_EVIDENCE_FAILED")
    try:
        if sender is None:
            payload = _post_fixed_local_rpc(
                target, "GetUserStatus", b"{}", timeout=2.0,
                max_bytes=_MAX_STATUS_BYTES,
            )
        else:
            payload = sender(target)
        return summarize_active_identity(payload)
    except NativeRpcError as exc:
        return _verdict(exc.code if exc.code in _SAFE_RPC_CODES
                        else "IDENTITY_OBSERVATION_FAILED")
    except Exception:
        return _verdict("IDENTITY_OBSERVATION_FAILED")
