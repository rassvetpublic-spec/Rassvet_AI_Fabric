"""Dependency-free, testable core. No credentials, no binary patches, no network.

This initial implementation never mutates a running Antigravity session.
It records a handoff plan; only a future validated adapter may execute one.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class State(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    NEEDS_HANDOFF = "needs_handoff"
    READY_TO_RESUME = "ready_to_resume"
    BLOCKED = "blocked"

@dataclass(frozen=True)
class Account:
    account_id: str
    enabled: bool = True
    quota_available: bool = True

@dataclass(frozen=True)
class Event:
    kind: str
    account_id: Optional[str]
    cursor: str
    description: str

@dataclass
class Supervisor:
    accounts: list[Account]
    active_id: Optional[str] = None
    state: State = State.IDLE
    cursor: str = ""
    events: list[Event] = field(default_factory=list)

    def _emit(self, kind: str, description: str) -> None:
        self.events.append(Event(kind, self.active_id, self.cursor, description))

    def start(self, account_id: str, cursor: str) -> None:
        if self.state not in (State.IDLE, State.READY_TO_RESUME):
            raise RuntimeError("cannot start from current state")
        if not any(a.account_id == account_id and a.enabled and a.quota_available for a in self.accounts):
            raise ValueError("account unavailable")
        self.active_id, self.cursor, self.state = account_id, cursor, State.RUNNING
        self._emit("started", "task checkpoint started")

    def observe_error(self, http_status: int) -> None:
        if self.state != State.RUNNING:
            raise RuntimeError("no running task")
        if http_status == 429:
            self.state = State.NEEDS_HANDOFF
            self._emit("quota_exhausted", "quota exhausted; task suspended")
        elif http_status in (401, 403):
            self.state = State.BLOCKED
            self._emit("authorization_blocked", "authorization/policy failure; no automatic rotation")
        else:
            self._emit("request_error", f"HTTP {http_status}; no automatic rotation")

    def plan_handoff(self) -> Optional[str]:
        if self.state != State.NEEDS_HANDOFF:
            raise RuntimeError("handoff not required")
        target = next((a.account_id for a in self.accounts
                       if a.account_id != self.active_id and a.enabled and a.quota_available), None)
        if target is None:
            self.state = State.BLOCKED
            self._emit("no_candidate", "no eligible account available")
            return None
        self._emit("handoff_planned", f"candidate={target}; explicit confirmation required")
        return target

    def confirm_handoff(self, target: str, session_validated: bool) -> None:
        """Called only after a trusted integration confirms the session switched."""
        if self.state != State.NEEDS_HANDOFF or not session_validated:
            raise RuntimeError("cannot confirm unvalidated session")
        if not any(a.account_id == target and a.enabled and a.quota_available for a in self.accounts):
            raise ValueError("target unavailable")
        self.active_id, self.state = target, State.READY_TO_RESUME
        self._emit("handoff_confirmed", "session validated; resume must be explicit")

    def checkpoint(self) -> dict:
        """Export only nonsecret state. No account tokens, credentials or prompts."""
        return {"state": self.state.value, "active_id": self.active_id,
                "cursor": self.cursor,
                "events": [e.__dict__ for e in self.events]}
