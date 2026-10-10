"""Strict, read-only parser for the Antigravity quota summary response shape.

This parser does not fetch quotas or use OAuth. Payloads may be untrusted;
it retains only known model groups, two quota windows and numeric fractions.
Never log or serialize raw responses, which might contain sensitive data.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from .pool import GroupQuota, ModelGroup, QuotaWindow


class QuotaParseError(ValueError):
    """Fixed-text parsing error; raw provider contents are never echoed."""


_MAX_BODY = 1024 * 1024
_MAX_GROUPS = 64
_MAX_BUCKETS = 64
_GROUPS = {
    "gemini models": ModelGroup.GEMINI,
    "claude and gpt models": ModelGroup.CLAUDE_GPT,
}


def _fraction(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not 0 <= value <= 1:
        return None
    return float(value)


def _reset_timestamp(raw: Any) -> float | None:
    if not isinstance(raw, str) or not raw or len(raw) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        epoch = parsed.timestamp()
        return epoch if math.isfinite(epoch) and epoch >= 0 else None
    except (ValueError, OverflowError, OSError):
        return None


def _document(payload: bytes | dict) -> dict:
    if isinstance(payload, bytes):
        if not 0 < len(payload) <= _MAX_BODY:
            raise QuotaParseError("quota response size is unsupported")
        try:
            payload = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise QuotaParseError("quota response is not valid JSON") from None
    if not isinstance(payload, dict):
        raise QuotaParseError("quota response object is required")
    body = payload.get("response", payload)
    if not isinstance(body, dict):
        raise QuotaParseError("quota response object is required")
    return body


def parse_quota_summary(
    payload: bytes | dict, *, observed_at: float
) -> dict[ModelGroup, GroupQuota]:
    """Extract trusted-shape observations; invalid/ambiguous data fails closed.

    Recognizes English 'Gemini Models' and 'Claude and GPT models' only.
    Unknown labels and missing quota windows never authorize selection.
    """
    if isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)):
        raise QuotaParseError("quota observation time invalid")
    if not math.isfinite(observed_at) or observed_at < 0:
        raise QuotaParseError("quota observation time invalid")
    body = _document(payload)
    groups = body.get("groups")
    if not isinstance(groups, list) or len(groups) > _MAX_GROUPS:
        raise QuotaParseError("quota groups unavailable")
    output: dict[ModelGroup, GroupQuota] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        label = group.get("displayName")
        if not isinstance(label, str) or len(label) > 80:
            continue
        canonical = " ".join(label.casefold().split())
        known = _GROUPS.get(canonical)
        if known is None:
            continue
        if known in output:
            raise QuotaParseError("ambiguous quota group")
        buckets = group.get("buckets")
        if not isinstance(buckets, list) or len(buckets) > _MAX_BUCKETS:
            raise QuotaParseError("invalid quota buckets")
        values: dict[str, QuotaWindow] = {}
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            window = bucket.get("window")
            if window not in ("5h", "weekly"):
                continue
            if window in values:
                raise QuotaParseError("ambiguous quota window")
            raw_disabled = bucket.get("disabled")
            # Missing/invalid disabled flag is UNKNOWN; never infer eligibility.
            disabled = raw_disabled if type(raw_disabled) is bool else None
            values[window] = QuotaWindow(
                _fraction(bucket.get("remainingFraction")),
                float(observed_at),
                reset_at=_reset_timestamp(bucket.get("resetTime")),
                disabled=disabled,
            )
        if "5h" in values and "weekly" in values:
            output[known] = GroupQuota(values["5h"], values["weekly"])
    return output
