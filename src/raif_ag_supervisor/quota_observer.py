"""Sanitized observations from the internal Standalone HTTPS quota RPC.

The quota source is associated with a running LS instance, NOT with any
particular RAiF Vault account until separately attested. No automatic
AccountPool registration or switching, no raw HTTP bodies in results.
"""
from __future__ import annotations

__version__ = "1.0.0"

import math
from typing import Callable

from .native_rpc import (
    LocalRpcTarget, NativeRpcError, invoke_native_quota_rpc,
)
from .pool import ModelGroup
from .quota_adapter import QuotaParseError, parse_quota_summary


def _failed(code: str) -> dict:
    return {
        "verdict": code, "source": "NATIVE_HTTPS_CONNECT_RPC",
        "account_identity_verified": False, "eligible_for_pool": False,
        "groups": [],
    }


def summarize_native_quota_response(payload: dict | bytes, *, observed_at: float) -> dict:
    """Discard everything but bounded known-group quota values and statuses."""
    parsed = parse_quota_summary(payload, observed_at=observed_at)
    output = []
    for group in (ModelGroup.GEMINI, ModelGroup.CLAUDE_GPT):
        snapshot = parsed.get(group)
        if snapshot is None:
            continue
        windows = {}
        for key, window in (("five_hour", snapshot.five_hour), ("weekly", snapshot.weekly)):
            windows[key] = {
                "remaining_fraction": window.remaining_fraction,
                "disabled": window.disabled,
                "status": window.status(observed_at).value,
                "reset_at_unix": window.reset_at,
            }
        output.append({"group": group.value, **windows})
    return {
        "verdict": "QUOTA_OBSERVED" if output else "NO_RECOGNIZED_QUOTA_GROUPS",
        "source": "NATIVE_HTTPS_CONNECT_RPC",
        "account_identity_verified": False,
        "eligible_for_pool": False,  # Do not map LS quota to one of 9 accounts by guess.
        "groups": output,
    }


def collect_native_quota(
    target: LocalRpcTarget, *, allow_quota_read: bool,
    ownership_verified: Callable[[], bool], observed_at: float,
    sender: Callable[..., dict] | None = None,
) -> dict:
    """Opt-in quota fetch with trusted owner recheck and safe aggregate only."""
    if allow_quota_read is not True:
        return _failed("RPC_QUOTA_OPT_IN_REQUIRED")
    if (not isinstance(observed_at, (int, float)) or isinstance(observed_at, bool)
            or not math.isfinite(observed_at) or observed_at < 0):
        return _failed("OBSERVATION_TIME_INVALID")
    if not callable(ownership_verified):
        return _failed("RPC_OWNER_EVIDENCE_REQUIRED")
    try:
        if ownership_verified() is not True:
            return _failed("RPC_OWNER_EVIDENCE_FAILED")
        request = sender or invoke_native_quota_rpc
        payload = request(
            target, allow_quota_read=True, ownership_verified=ownership_verified,
        )
        return summarize_native_quota_response(payload, observed_at=float(observed_at))
    except NativeRpcError as exc:
        return _failed(exc.code)
    except QuotaParseError:
        return _failed("QUOTA_SCHEMA_UNSUPPORTED")
    except Exception:
        # Arbitrary injected callback errors must not leak user context.
        return _failed("QUOTA_OBSERVATION_FAILED")
