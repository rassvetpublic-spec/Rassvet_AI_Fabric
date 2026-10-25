"""W2 receipt evidence: bounded, fail-closed *source-only* verification.

This module has no production authority. In-memory grants and synthetic sinks are
NOT a signed owner MTD or a host effect attestation; no real-provider completion
may be inferred from a successful readback alone.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Optional

from .effect_receipt_contract import EffectIntent, TargetEffectReceipt, VerifiedReadback

MAX_READBACK_BYTES = 16 * 1024 * 1024


class VerifierError(ValueError):
    """The grant or target evidence cannot be verified safely."""


@dataclass(frozen=True)
class PinnedGrant:
    grant_ref: str
    task_id: str
    host_id: str
    target_id: str
    deadline_utc: float
    provider: str
    operation_id: str
    envelope_id: str
    payload_sha256: str
    issuer_ref: str


class LocalTrustedGrantRegistry:
    """Test-only grant inventory; real authority needs an external trusted issuer.

    Without an explicitly supplied verifier this registry authorizes NOTHING.
    Inserting a grant into this local dict is not proof that the owner signed it.
    """

    def __init__(
        self,
        expected_host_id: str = "RASSVET_DESKTOP",
        *,
        verify_issuer: Callable[[PinnedGrant, EffectIntent], bool] | None = None,
    ):
        self.expected_host_id = expected_host_id
        self._verify_issuer = verify_issuer
        self._grants: dict[str, PinnedGrant] = {}

    def register_grant(
        self,
        grant_ref: str,
        task_id: str,
        target_id: str,
        deadline_utc: float,
        host_id: Optional[str] = None,
        *,
        provider: str | None = None,
        operation_id: str | None = None,
        envelope_id: str | None = None,
        payload_sha256: str | None = None,
        issuer_ref: str | None = None,
    ) -> None:
        values = (grant_ref, task_id, target_id, provider, operation_id,
                  envelope_id, payload_sha256, issuer_ref)
        if any(not isinstance(v, str) or not v or len(v) > 256 for v in values):
            raise VerifierError("GRANT_BINDING_MISSING")
        if not isinstance(deadline_utc, (int, float)) or isinstance(deadline_utc, bool):
            raise VerifierError("GRANT_DEADLINE_INVALID")
        self._grants[grant_ref] = PinnedGrant(
            grant_ref=grant_ref,
            task_id=task_id,
            host_id=host_id or self.expected_host_id,
            target_id=target_id,
            deadline_utc=float(deadline_utc),
            provider=provider,
            operation_id=operation_id,
            envelope_id=envelope_id,
            payload_sha256=payload_sha256,
            issuer_ref=issuer_ref,
        )

    def revoke_grant(self, grant_ref: str) -> None:
        self._grants.pop(grant_ref, None)

    def authorize(self, intent: EffectIntent) -> bool:
        """Fail closed for unverified issuer, mismatches, or missing grant."""
        if not isinstance(intent, EffectIntent) or not callable(self._verify_issuer):
            return False
        grant = self._grants.get(intent.owner_grant_ref)
        if grant is None:
            return False
        if grant.host_id != self.expected_host_id:
            return False
        comparisons = (
            (grant.grant_ref, intent.owner_grant_ref),
            (grant.task_id, intent.task_id),
            (grant.target_id, intent.target_id),
            (grant.host_id, intent.host_id),
            (grant.provider, intent.provider),
            (grant.operation_id, intent.operation_id),
            (grant.envelope_id, intent.envelope_id),
            (grant.payload_sha256, intent.payload_sha256),
        )
        if any(not hmac.compare_digest(a, b) for a, b in comparisons):
            return False
        if grant.deadline_utc < intent.lease_deadline_utc:
            return False
        try:
            return self._verify_issuer(grant, intent) is True
        except Exception:
            return False


class LocalTargetReadbackVerifier:
    """Bounded readback of a pinned file, not a production effect attestation.

    Only file revision sha256:<actual file digest> is independently established.
    Symlink/reparse directories, Windows ADS and any parent traversal are denied.
    There is no cross-platform hard guarantee against concurrent hostile inode
    swaps; callers MUST NOT treat this as authority for real-provider COMPLETE.
    """

    def __init__(
        self,
        expected_host_id: str = "RASSVET_DESKTOP",
        verifier_ref: str = "local-fs-readback-SOURCE_ONLY-v2",
    ):
        self.expected_host_id = expected_host_id
        self.verifier_ref = verifier_ref
        self._target_roots: dict[str, Path] = {}
        self._synthetic_sinks: dict[str, dict[str, str]] = {}

    def register_target_root(self, target_id: str, root_path: Path) -> None:
        root = Path(root_path)
        if not root.is_dir() or root.is_symlink():
            raise VerifierError("ROOT_NOT_TRUSTED")
        self._target_roots[target_id] = root.resolve(strict=True)

    def register_synthetic_sink(self, target_id: str, sink_store: dict[str, str]) -> None:
        """Retained for old test callers; never promoted as host proof."""
        self._synthetic_sinks[target_id] = sink_store

    @staticmethod
    def _safe_components(operation_id: str) -> tuple[str, ...] | None:
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 256:
            return None
        if "\\" in operation_id or ":" in operation_id or "\x00" in operation_id:
            return None
        posix = PurePosixPath(operation_id)
        win = PureWindowsPath(operation_id)
        if posix.is_absolute() or win.is_absolute() or win.drive or win.root:
            return None
        if any(p in ("", ".", "..") for p in operation_id.split("/")):
            return None
        return tuple(posix.parts)

    @staticmethod
    def _unsafe_link_or_reparse(path: Path) -> bool:
        try:
            info = path.lstat()
            attrs = getattr(info, "st_file_attributes", 0)
            return stat.S_ISLNK(info.st_mode) or bool(attrs & 0x400)
        except (OSError, ValueError):
            return True

    @classmethod
    def _bounded_bytes(cls, root: Path, operation_id: str) -> bytes | None:
        components = cls._safe_components(operation_id)
        if not components or cls._unsafe_link_or_reparse(root):
            return None
        try:
            anchor = root.resolve(strict=True)
            candidate = anchor
            # Check every ancestor independently, not only the final path.
            for part in components:
                candidate = candidate / part
                if cls._unsafe_link_or_reparse(candidate):
                    return None
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(anchor)  # path-component containment, NOT startswith
            if not resolved.is_file():
                return None
            before = resolved.stat()
            if before.st_size > MAX_READBACK_BYTES or before.st_nlink != 1:
                return None
            # O_NOFOLLOW protects the final component where the platform supports it.
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(resolved, flags)
            try:
                opened = os.fstat(fd)
                if (opened.st_ino, opened.st_dev) != (before.st_ino, before.st_dev):
                    return None
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    data = stream.read(MAX_READBACK_BYTES + 1)
                after = os.fstat(fd)
                if len(data) > MAX_READBACK_BYTES:
                    return None
                if ((after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns)
                        != (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns)):
                    return None
                if cls._unsafe_link_or_reparse(candidate):
                    return None
                return data
            finally:
                os.close(fd)
        except (OSError, ValueError, RuntimeError):
            return None

    def verify_target(self, intent: EffectIntent, receipt: TargetEffectReceipt) -> Optional[VerifiedReadback]:
        if not isinstance(intent, EffectIntent) or not isinstance(receipt, TargetEffectReceipt):
            return None
        if intent.host_id != self.expected_host_id or receipt.host_id != self.expected_host_id:
            return None
        if intent.target_id not in self._target_roots:
            # Synthetic sinks are deliberately NOT authority evidence.
            return None
        root = self._target_roots[intent.target_id]
        content = self._bounded_bytes(root, receipt.operation_id)
        if content is None:
            return None
        actual_sha = hashlib.sha256(content).hexdigest()
        revision = "sha256:" + actual_sha
        if not hmac.compare_digest(revision, receipt.target_revision):
            return None
        return VerifiedReadback(
            target_id=intent.target_id,
            host_id=self.expected_host_id,
            target_revision=revision,
            content_sha256=actual_sha,
            verifier_ref=self.verifier_ref,
        )
