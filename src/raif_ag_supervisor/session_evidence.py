"""CP-54C1: non-identifying process evidence for offline planning.

PID alone, quota/UI matches and local auth flags cannot prove account identity.
This module never obtains account handles, credentials or identity attributes.
"""
from __future__ import annotations

__version__ = "1.0.0"

import re
from dataclasses import dataclass

_FILETIME = re.compile(r"[0-9a-f]{16}\Z")


@dataclass(frozen=True)
class ProcessStamp:
    pid: int
    creation_filetime: str

    def __post_init__(self) -> None:
        if type(self.pid) is not int or not 0 < self.pid <= 0xFFFFFFFF:
            raise ValueError("PROCESS_PID_INVALID")
        if not isinstance(self.creation_filetime, str) or not _FILETIME.fullmatch(self.creation_filetime) or int(self.creation_filetime, 16) == 0:
            raise ValueError("PROCESS_FILETIME_INVALID")


def process_relation(before: ProcessStamp | None, after: ProcessStamp | None) -> str:
    """Return only a process-instance relation, never identity attestation."""
    if not isinstance(before, ProcessStamp) or not isinstance(after, ProcessStamp):
        return "PROCESS_UNVERIFIED"
    if before.pid == after.pid and before.creation_filetime == after.creation_filetime:
        return "SAME_PROCESS_INSTANCE"
    return "PROCESS_INSTANCE_CHANGED"


def bounded_session_evidence(before: ProcessStamp | None, after: ProcessStamp | None,
                             _untrusted_status: object = None) -> dict:
    """Accept untrusted status for analysis only; do not propagate raw data."""
    return {
        "process_relation": process_relation(before, after),
        "active_account_identity": "IDENTITY_UNVERIFIED",
        "account_identity_verified": False,
        "provider_access_verified": False,
        "hot_swap_verified": False,
        "stream_continuity_verified": False,
        "eligible_for_pool": False,
    }
