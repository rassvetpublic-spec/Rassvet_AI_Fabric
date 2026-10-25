"""Source-only, transactional W2 SQLite schema candidate.

Validates complete canonical schema on EVERY idempotent read, not only table
names. Production databases MUST NOT be migrated by this offline candidate.
"""
from __future__ import annotations

import re
import sqlite3
from .store import FabricError, FabricStore

SCHEMA_TABLES = {
    "effect_intents": """
        CREATE TABLE IF NOT EXISTS effect_intents (
            task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            target_id TEXT NOT NULL,
            host_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            envelope_id TEXT NOT NULL,
            lease_epoch INTEGER NOT NULL CHECK(lease_epoch > 0),
            lease_deadline_utc REAL NOT NULL,
            payload_sha256 TEXT NOT NULL,
            owner_grant_ref TEXT NOT NULL,
            created_at REAL NOT NULL
        )""",
    "effect_operations": """
        CREATE TABLE IF NOT EXISTS effect_operations (
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
            target_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            lease_epoch INTEGER NOT NULL CHECK(lease_epoch > 0),
            expected_revision TEXT NOT NULL,
            phase TEXT NOT NULL CHECK(phase IN
                ('PREPARED','MAY_HAVE_RUN','APPLIED_VERIFIED',
                 'NO_EFFECT_VERIFIED','UNKNOWN_OUTCOME','BLOCKED_RECONCILE')),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY(target_id, operation_id)
        )""",
    "effect_receipts": """
        CREATE TABLE IF NOT EXISTS effect_receipts (
            receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            verdict TEXT NOT NULL CHECK(verdict IN
                ('APPLIED_VERIFIED','NO_EFFECT_VERIFIED')),
            target_revision TEXT NOT NULL,
            applied_sha256 TEXT NOT NULL,
            evidence_sha256 TEXT NOT NULL,
            readback_class TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(target_id, operation_id),
            FOREIGN KEY(target_id, operation_id)
                REFERENCES effect_operations(target_id, operation_id)
        )""",
}

SCHEMA_INDICES = {
    "idx_effect_intents_host": "CREATE INDEX IF NOT EXISTS idx_effect_intents_host ON effect_intents(host_id, target_id)",
    "idx_effect_task": "CREATE INDEX IF NOT EXISTS idx_effect_task ON effect_operations(task_id, phase)",
}
SCHEMA_TRIGGERS = {
    f"immutable_effect_receipt_{verb.lower()}": (
        f"CREATE TRIGGER IF NOT EXISTS immutable_effect_receipt_{verb.lower()} "
        f"BEFORE {verb} ON effect_receipts "
        "BEGIN SELECT RAISE(ABORT, 'EFFECT_RECEIPT_IMMUTABLE'); END"
    )
    for verb in ("UPDATE", "DELETE")
}


def _normalized_ddl(statement: str | None) -> str:
    """Strict canonical-structure comparison across insignificant SQL spacing."""
    if not isinstance(statement, str):
        return ""
    without_create_guard = re.sub(r"\bIF\s+NOT\s+EXISTS\b", "", statement, flags=re.IGNORECASE)
    return re.sub(r"\s+", "", without_create_guard).lower().rstrip(";")


def _validate_v2(store: FabricStore) -> None:
    """Reject absent/corrupted tables, constraints, triggers and indices."""
    for category, names in (
        ("table", SCHEMA_TABLES),
        ("index", SCHEMA_INDICES),
        ("trigger", SCHEMA_TRIGGERS),
    ):
        for name, expected in names.items():
            row = store.db.execute(
                "SELECT sql FROM sqlite_master WHERE type=? AND name=?",
                (category, name),
            ).fetchone()
            if row is None or _normalized_ddl(row[0]) != _normalized_ddl(expected):
                raise FabricError(f"W2_SCHEMA_CORRUPT:{category}:{name}")
    broken_fk = store.db.execute("PRAGMA foreign_key_check").fetchone()
    if broken_fk is not None:
        raise FabricError("W2_SCHEMA_FOREIGN_KEY_CORRUPT")


def migrate_store_v1_to_v2(store: FabricStore) -> bool:
    """Migrate only explicitly initialized disposable stores; fail closed on drift.

    Returns True on v1->v2 creation and False on structurally valid v2. This
    function provides schema semantics, not a real-provider execution permit.
    """
    if not isinstance(store, FabricStore):
        raise FabricError("INVALID_FABRIC_STORE")
    with store.atomic():
        row = store.db.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            raise FabricError("W2_SCHEMA_VERSION_MISSING")
        current = row[0]
        if current == "2":
            _validate_v2(store)
            return False
        if current != "1":
            raise FabricError(f"W2_SCHEMA_UNSUPPORTED:{current}")

        try:
            for ddl in SCHEMA_TABLES.values():
                store.db.execute(ddl)
            for ddl in SCHEMA_INDICES.values():
                store.db.execute(ddl)
            for ddl in SCHEMA_TRIGGERS.values():
                store.db.execute(ddl)
        except sqlite3.DatabaseError as exc:
            raise FabricError("W2_SCHEMA_CORRUPT:ddl") from exc
        _validate_v2(store)
        changed = store.db.execute(
            "UPDATE meta SET value='2' WHERE key='schema_version' AND value='1'"
        ).rowcount
        if changed != 1:
            raise FabricError("W2_SCHEMA_VERSION_CAS_FAILED")
    return True
