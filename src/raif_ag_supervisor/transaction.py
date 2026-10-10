"""Transactional import into a user-controlled credential vault.

Secrets are parsed in memory; only generated opaque IDs are exposed in
checkpoints. This module never reads the actual exported file by itself.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Protocol

from .importer import parse_manifest


class WritableVault(Protocol):
    def put(self, account_id: str, secret: str) -> None: ...
    def has(self, account_id: str) -> bool: ...
    def delete(self, account_id: str) -> None: ...


@dataclass(frozen=True)
class ImportedAccount:
    account_id: str
    email: str = field(repr=False)


class ImportTransactionError(RuntimeError):
    """Sanitized error; never includes credential contents."""


def import_into_vault(raw_manifest: bytes, vault: WritableVault) -> list[ImportedAccount]:
    """Validate the whole manifest, then import under generated, opaque IDs.

    On errors, attempts rollback of all newly allocated targets. This is
    not a crash-safe atomic transaction: a killed process may leave orphaned
    entries. Do not use with an untrusted vault implementation.
    """
    records = parse_manifest(raw_manifest)
    allocated: list[str] = []
    completed: list[ImportedAccount] = []
    try:
        for record in records:
            account_id = "raif-" + secrets.token_hex(16)
            if vault.has(account_id):
                raise ImportTransactionError("generated account ID collision")
            # Track before writing to cover a partial failure inside put().
            allocated.append(account_id)
            vault.put(account_id, record.credential)
            completed.append(ImportedAccount(account_id, record.email))
        return completed
    except Exception:
        rollback_failed = False
        for account_id in reversed(allocated):
            try:
                vault.delete(account_id)
            except Exception:
                rollback_failed = True
        if rollback_failed:
            raise ImportTransactionError(
                "import failed; rollback incomplete, inspect RAiF vault entries"
            ) from None
        raise ImportTransactionError("import failed; newly allocated entries reverted") from None
