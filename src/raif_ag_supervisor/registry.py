"""Crash-recoverable registry of opaque account IDs, without credentials.

This is a single-writer prototype. Other processes must not modify registry
files concurrently. The journal allows recovery after an interrupted import.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .importer import parse_manifest


_ID_RE = re.compile(r"raif-[0-9a-f]{32}\Z")
_MAX_FILE = 1024 * 1024


class RegistryError(RuntimeError):
    """Safe diagnostic that contains no user account or credential values."""


class RegistryVault(Protocol):
    def put(self, account_id: str, secret: str) -> None: ...
    def has(self, account_id: str) -> bool: ...
    def delete(self, account_id: str) -> None: ...


def _validate_ids(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > 200:
        raise RegistryError("invalid registry account list")
    if any(not isinstance(x, str) or not _ID_RE.fullmatch(x) for x in value):
        raise RegistryError("invalid opaque account ID")
    if len(set(value)) != len(value):
        raise RegistryError("duplicate opaque account ID")
    return value


def _read(path: Path, key: str) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as handle:
            body = handle.read(_MAX_FILE + 1)
        if len(body) > _MAX_FILE:
            raise RegistryError("registry metadata is oversized")
        data = json.loads(body)
        if not isinstance(data, dict) or set(data) != {"version", key} or type(data["version"]) is not int or data["version"] != 1:
            raise RegistryError("unknown registry metadata schema")
        ids = _validate_ids(data[key])
        if key == "allocated" and not ids:
            raise RegistryError("empty pending journal is invalid")
        return ids
    except (OSError, ValueError, UnicodeError, TypeError) as error:
        raise RegistryError("cannot read registry metadata") from None


def _write(path: Path, key: str, ids: list[str]) -> None:
    value = {"version": 1, key: _validate_ids(ids)}
    encoded = (json.dumps(value, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
    fd, tmp_name = tempfile.mkstemp(prefix=".raif-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


@dataclass
class LocalAccountRegistry:
    """Persistent nonsecret metadata and rollback journal.

    Caller provides a user-private directory outside the Git repository.
    Only account IDs are persisted; email, refresh token and prompt are never
    written. Existing third-party Credential Manager targets are untouched.
    """

    root: Path
    _mutex: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    @property
    def registry_path(self) -> Path:
        return self.root / "accounts.json"

    @property
    def pending_path(self) -> Path:
        return self.root / "pending-import.json"

    def ids(self) -> tuple[str, ...]:
        with self._mutex:
            return tuple(_read(self.registry_path, "accounts"))

    def recover(self, vault: RegistryVault) -> str:
        """Resolve an interrupted import. Never delete committed IDs."""
        with self._mutex:
            if not self.pending_path.exists():
                return "clean"
            pending = _read(self.pending_path, "allocated")
            committed = set(_read(self.registry_path, "accounts"))
            overlap = sum(handle in committed for handle in pending)
            if 0 < overlap < len(pending):
                raise RegistryError("ambiguous partially committed registry; manual review")
            if overlap == len(pending):
                self.pending_path.unlink()
                return "committed"
            try:
                for handle in reversed(pending):
                    vault.delete(handle)
            except Exception:
                raise RegistryError("rollback incomplete; pending journal retained") from None
            self.pending_path.unlink()
            return "rolled_back"

    def import_manifest(self, raw: bytes, vault: RegistryVault) -> tuple[str, ...]:
        """Import a validated manifest with write-ahead journal and recovery."""
        records = parse_manifest(raw)
        with self._mutex:
            if self.pending_path.exists():
                raise RegistryError("pending import requires recovery before new import")
            existing = _read(self.registry_path, "accounts")
            if len(existing) + len(records) > 200:
                raise RegistryError("registry capacity exceeded")
            allocated = ["raif-" + secrets.token_hex(16) for _ in records]
            if len(set(allocated)) != len(allocated):
                raise RegistryError("generated ID collision")
            if any(handle in existing or vault.has(handle) for handle in allocated):
                raise RegistryError("generated ID conflicts with existing entry")
            # Write journal BEFORE putting any credentials in the native vault.
            _write(self.pending_path, "allocated", allocated)
            try:
                for handle, record in zip(allocated, records):
                    vault.put(handle, record.credential)
                _write(self.registry_path, "accounts", existing + allocated)
            except Exception:
                # If a vault call fails, preserve the journal if rollback fails.
                self.recover(vault)
                raise RegistryError("import failed; staged credentials rolled back") from None
            # Registry commit is durable before removing the pending journal.
            # A crash here is resolved by recover() without deleting credentials.
            self.pending_path.unlink()
            return tuple(allocated)

    def __repr__(self) -> str:
        return "LocalAccountRegistry(metadata-only)"
