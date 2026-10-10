"""CP-54C1 offline-only rollback fault harness.

A deterministic *in-memory* credential canary simulator. No passwords,
CredMan, DPAPI, Language Server, OS processes, or external endpoints.
Its success is not proof of restoration of an actual Standalone session.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SyntheticFault(str, Enum):
    NONE = "none"
    FAIL_BEFORE_WRITE = "fail_before_write"
    CRASH_AFTER_WRITE = "crash_after_write"
    READBACK_MISMATCH = "readback_mismatch"
    RESTORE_FAILURE = "restore_failure"
    PID_REUSED = "pid_reused"
    CONCURRENT_OPERATION = "concurrent_operation"


@dataclass(frozen=True)
class SyntheticRollbackReport:
    verdict: str
    phase: str
    candidate_writes: int
    restore_attempts: int
    original_restored: bool
    journal_preceded_write: bool
    live_credentials_read: bool = False
    account_identity_verified: bool = False
    real_rollback_verified: bool = False

    def safe_dict(self) -> dict:
        return {
            "verdict": self.verdict, "phase": self.phase,
            "candidate_writes": self.candidate_writes,
            "restore_attempts": self.restore_attempts,
            "original_restored": self.original_restored,
            "journal_preceded_write": self.journal_preceded_write,
            "live_credentials_read": False,
            "account_identity_verified": False,
            "real_rollback_verified": False,
        }


def simulate_rollback(fault: SyntheticFault = SyntheticFault.NONE) -> SyntheticRollbackReport:
    """Exercise bounded synthetic failures without accepting caller secret data.

    The immutable strings are just test-state labels, not credential values.
    A mock journal is always durable *in the simulation* before candidate write.
    """
    if type(fault) is not SyntheticFault:
        raise ValueError("SYNTHETIC_FAULT_UNSUPPORTED")
    if fault is SyntheticFault.PID_REUSED:
        return SyntheticRollbackReport("BLOCKED_STALE_PROCESS", "PRECHECK", 0, 0, True, False)
    if fault is SyntheticFault.CONCURRENT_OPERATION:
        return SyntheticRollbackReport("BLOCKED_ONE_WRITER_GATE", "PRECHECK", 0, 0, True, False)

    journal_written = True
    original = "SYNTHETIC_ORIGIN"
    state = original
    if fault is SyntheticFault.FAIL_BEFORE_WRITE:
        return SyntheticRollbackReport("NO_WRITE_SAFE_FAIL", "PREPARED", 0, 0, True, journal_written)

    state = "SYNTHETIC_CANDIDATE"
    if fault is SyntheticFault.CRASH_AFTER_WRITE:
        return SyntheticRollbackReport("RECOVERY_REQUIRED", "PENDING_REVIEW", 1, 0, False, journal_written)
    if fault is SyntheticFault.READBACK_MISMATCH:
        state = "SYNTHETIC_DIVERGED"
    if fault is SyntheticFault.RESTORE_FAILURE:
        return SyntheticRollbackReport("MANUAL_RECOVERY_REQUIRED", "RESTORE_ATTEMPTED", 1, 1, False, journal_written)

    # In-memory restore and readback: cannot establish actual provider identity.
    state = original
    return SyntheticRollbackReport(
        "SYNTHETIC_RESTORE_VERIFIED" if fault is SyntheticFault.NONE
        else "SYNTHETIC_RESTORE_VERIFIED_AFTER_MISMATCH",
        "RESTORE_VERIFIED", 1, 1, state == original, journal_written,
    )
