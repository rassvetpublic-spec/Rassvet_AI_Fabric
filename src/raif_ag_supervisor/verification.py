"""Evidence-based acceptance gate for live Standalone account switching.

This module does not switch accounts or read credentials. A future trusted
Windows observer must supply process-instance, account-identity and stream
continuity evidence. Synthetic flags alone are not runtime proof.
"""

__version__ = "1.0.0"
from dataclasses import dataclass, field
from enum import Enum


class SwitchVerdict(str, Enum):
    INCONCLUSIVE = "inconclusive"
    PROCESS_RESTARTED = "process_restarted"
    ACCOUNT_UNCHANGED = "account_unchanged"
    WRONG_ACCOUNT = "wrong_account"
    ACCOUNT_CHANGED = "account_changed_stream_unproven"
    VERIFIED = "verified"


@dataclass(frozen=True)
class SessionEvidence:
    server_pid: int | None
    server_start_marker: str | None
    account_handle: str | None = field(default=None, repr=False)
    identity_verified: bool = False
    stream_continuity_verified: bool = False


@dataclass(frozen=True)
class SwitchAssessment:
    verdict: SwitchVerdict
    reason: str


def evaluate_handoff(
    before: SessionEvidence,
    after: SessionEvidence,
    target_handle: str,
) -> SwitchAssessment:
    """Accept only same server instance + verified identity + stream continuation.

    The caller must independently confirm the provenance of attestation flags.
    Neither a changed Credential Manager record nor an unchanged PID alone
    proves that the Standalone session switched.
    """
    if (before.server_pid is None or after.server_pid is None or
            not before.server_start_marker or not after.server_start_marker):
        return SwitchAssessment(SwitchVerdict.INCONCLUSIVE, "server identity unavailable")
    if ((before.server_pid, before.server_start_marker) !=
            (after.server_pid, after.server_start_marker)):
        return SwitchAssessment(SwitchVerdict.PROCESS_RESTARTED, "server instance changed")
    if not before.identity_verified or not after.identity_verified:
        return SwitchAssessment(SwitchVerdict.INCONCLUSIVE, "account identity not attested")
    if not before.account_handle or not after.account_handle or not target_handle:
        return SwitchAssessment(SwitchVerdict.INCONCLUSIVE, "account handle unavailable")
    if before.account_handle == after.account_handle:
        return SwitchAssessment(SwitchVerdict.ACCOUNT_UNCHANGED, "no account identity change")
    if after.account_handle != target_handle:
        return SwitchAssessment(SwitchVerdict.WRONG_ACCOUNT, "unexpected account identity")
    if not after.stream_continuity_verified:
        return SwitchAssessment(
            SwitchVerdict.ACCOUNT_CHANGED,
            "account changed but in-flight task continuity not attested",
        )
    return SwitchAssessment(SwitchVerdict.VERIFIED, "same process and verified task continuity")
