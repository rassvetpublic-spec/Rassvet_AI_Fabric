"""Quota-aware account-pool planner for Windows Antigravity Standalone.

Pure offline logic. NO browser automation, Credential Manager mutation,
OAuth exchange, Language Server injection, or account switch execution.
Only a trusted source may later supply quota observations / 429 events.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable

_ACCOUNT_ID = re.compile(r"raif-[0-9a-f]{32}\Z")
_MAX_SNAPSHOT_AGE = 300.0


class PoolError(ValueError):
    """Safe validation error without identifying information."""


class ModelGroup(str, Enum):
    GEMINI = "gemini"
    CLAUDE_GPT = "claude_gpt"


class QuotaStatus(str, Enum):
    READY = "ready"
    UNKNOWN = "unknown"
    STALE = "stale"
    EXHAUSTED = "exhausted"
    DISABLED = "disabled"


def _timestamp(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PoolError(f"invalid {name}")
    if not math.isfinite(value) or value < 0:
        raise PoolError(f"invalid {name}")
    return float(value)


def _group(value: ModelGroup) -> ModelGroup:
    if not isinstance(value, ModelGroup):
        raise PoolError("unsupported model group")
    return value


def _account(value: str) -> str:
    if not isinstance(value, str) or not _ACCOUNT_ID.fullmatch(value):
        raise PoolError("invalid opaque account handle")
    return value


@dataclass(frozen=True)
class QuotaWindow:
    remaining_fraction: float | None
    observed_at: float
    reset_at: float | None = None
    disabled: bool = False

    def __post_init__(self) -> None:
        _timestamp(self.observed_at, "observation timestamp")
        if self.reset_at is not None:
            _timestamp(self.reset_at, "reset timestamp")
        if not isinstance(self.disabled, bool):
            raise PoolError("invalid disabled flag")
        value = self.remaining_fraction
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PoolError("invalid remaining quota")
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise PoolError("invalid remaining quota")

    def status(self, now: float, max_age: float = _MAX_SNAPSHOT_AGE) -> QuotaStatus:
        timestamp = _timestamp(now, "current timestamp")
        if self.disabled:
            return QuotaStatus.DISABLED
        if self.remaining_fraction is None:
            return QuotaStatus.UNKNOWN
        if timestamp < self.observed_at - 30 or timestamp - self.observed_at > max_age:
            return QuotaStatus.STALE
        # Even when reset_at is in the past, never infer that a quota refilled.
        if self.remaining_fraction == 0:
            return QuotaStatus.EXHAUSTED
        return QuotaStatus.READY


@dataclass(frozen=True)
class GroupQuota:
    five_hour: QuotaWindow
    weekly: QuotaWindow

    def score(self, now: float, max_age: float = _MAX_SNAPSHOT_AGE) -> float | None:
        if self.five_hour.status(now, max_age) != QuotaStatus.READY:
            return None
        if self.weekly.status(now, max_age) != QuotaStatus.READY:
            return None
        assert self.five_hour.remaining_fraction is not None
        assert self.weekly.remaining_fraction is not None
        return float(min(self.five_hour.remaining_fraction, self.weekly.remaining_fraction))


@dataclass(frozen=True)
class HandoffPlan:
    source_handle: str = field(repr=False)
    target_handle: str = field(repr=False)
    model_group: ModelGroup
    minimum_remaining_fraction: float
    requires_live_session_validation: bool = True

    def safe_summary(self) -> dict:
        """Output never includes account handles, names or credentials."""
        return {
            "candidate_found": True,
            "model_group": self.model_group.value,
            "minimum_remaining_percent": round(self.minimum_remaining_fraction * 100, 1),
            "live_session_validation_required": True,
            "account_switched": False,
        }


class AccountPool:
    """Select a candidate on a trusted 429. Never perform the switch.

    Credentials only checked for presence, not read. All quota snapshots are
    memory-only and must come from independently validated observations.
    """
    def __init__(
        self,
        registered_handles: Iterable[str],
        credential_exists: Callable[[str], bool],
        freshness_seconds: float = _MAX_SNAPSHOT_AGE,
        retry_cooldown_seconds: float = 300.0,
    ) -> None:
        handles = tuple(_account(h) for h in registered_handles)
        if not handles or len(set(handles)) != len(handles) or len(handles) > 200:
            raise PoolError("invalid registered account set")
        if not callable(credential_exists):
            raise PoolError("credential lookup unavailable")
        self.handles = handles
        self._lookup = credential_exists
        self.freshness_seconds = _timestamp(freshness_seconds, "freshness")
        self.retry_cooldown_seconds = _timestamp(retry_cooldown_seconds, "cooldown")
        if self.freshness_seconds == 0:
            raise PoolError("freshness must be positive")
        self._quota: dict[tuple[str, ModelGroup], GroupQuota] = {}
        self._blocked: set[str] = set()
        self._disabled: set[str] = set()
        self._cooldown_until: dict[tuple[str, ModelGroup], float] = {}
        self._exhausted: set[tuple[str, ModelGroup]] = set()

    def _check(self, handle: str) -> None:
        if _account(handle) not in self.handles:
            raise PoolError("account not registered")

    def record_quota(self, handle: str, group: ModelGroup, snapshot: GroupQuota) -> None:
        self._check(handle)
        key = (handle, _group(group))
        if not isinstance(snapshot, GroupQuota):
            raise PoolError("invalid quota snapshot")
        self._quota[key] = snapshot
        # A fresh observation is evidence for the new amount, but an earlier
        # 429 still requires cooldown before retrying the same account.

    def enable(self, handle: str, enabled: bool) -> None:
        self._check(handle)
        if not isinstance(enabled, bool):
            raise PoolError("enabled must be boolean")
        if enabled:
            self._disabled.discard(handle)
        else:
            self._disabled.add(handle)

    def record_http_error(
        self, handle: str, group: ModelGroup, status: int, observed_at: float
    ) -> str:
        self._check(handle)
        group = _group(group)
        now = _timestamp(observed_at, "error timestamp")
        if type(status) is not int:
            raise PoolError("invalid HTTP status")
        if status in (401, 403):
            self._blocked.add(handle)
            self._exhausted.discard((handle, group))
            return "authorization_blocked"
        if status == 429:
            self._exhausted.add((handle, group))
            self._cooldown_until[(handle, group)] = now + self.retry_cooldown_seconds
            return "quota_exhausted"
        return "ignored"

    def propose_after_429(
        self, active_handle: str, group: ModelGroup, now: float
    ) -> HandoffPlan | None:
        self._check(active_handle)
        group = _group(group)
        now = _timestamp(now, "current timestamp")
        if active_handle in self._blocked or (active_handle, group) not in self._exhausted:
            return None
        candidates: list[tuple[float, int, str]] = []
        for i, handle in enumerate(self.handles):
            if handle == active_handle or handle in self._blocked or handle in self._disabled:
                continue
            if now < self._cooldown_until.get((handle, group), 0):
                continue
            quota = self._quota.get((handle, group))
            if quota is None:
                continue
            score = quota.score(now, self.freshness_seconds)
            if score is None:
                continue
            try:
                if not self._lookup(handle):
                    continue
            except Exception:
                # Fail closed if the trusted local credential vault is unavailable.
                continue
            candidates.append((-score, i, handle))
        if not candidates:
            return None
        candidates.sort()
        best = candidates[0]
        return HandoffPlan(
            source_handle=active_handle, target_handle=best[2],
            model_group=group, minimum_remaining_fraction=-best[0],
        )

    def safe_summary(self, group: ModelGroup, now: float) -> dict:
        group = _group(group)
        now = _timestamp(now, "current timestamp")
        ready = 0
        for handle in self.handles:
            if handle in self._blocked or handle in self._disabled:
                continue
            quota = self._quota.get((handle, group))
            if quota and quota.score(now, self.freshness_seconds) is not None:
                try:
                    ready += bool(self._lookup(handle))
                except Exception:
                    pass
        return {
            "registered_accounts": len(self.handles),
            "ready_candidates": ready,
            "blocked_accounts": len(self._blocked),
            "disabled_accounts": len(self._disabled),
            "model_group": group.value,
            "secrets_read": False,
            "automatic_switch": False,
        }


def synthetic_demo() -> dict:
    """Safe demonstration with invented handles and no real vault access."""
    first = "raif-" + "a" * 32
    second = "raif-" + "b" * 32
    now = 1_000_000.0
    pool = AccountPool((first, second), lambda handle: handle == second)
    full = GroupQuota(QuotaWindow(.87, now), QuotaWindow(.44, now))
    pool.record_quota(second, ModelGroup.GEMINI, full)
    pool.record_http_error(first, ModelGroup.GEMINI, 429, now)
    plan = pool.propose_after_429(first, ModelGroup.GEMINI, now)
    return {
        "mode": "synthetic_only",
        "pool": pool.safe_summary(ModelGroup.GEMINI, now),
        "handoff": plan.safe_summary() if plan else {"candidate_found": False},
    }


if __name__ == "__main__":
    print(json.dumps(synthetic_demo(), sort_keys=True))
