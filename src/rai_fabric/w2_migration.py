"""Идемпотентная миграция схемы W2 для FabricStore (L3 / W2).

Добавляет поддержку effect_intents, effect_operations, effect_receipts без удаления существующих данных.
Статус: CANDIDATE_ONLY (не запускается на боевой БД без отдельного MTD).
"""
from __future__ import annotations

import sqlite3
from .store import FabricError, FabricStore


def migrate_store_v1_to_v2(store: FabricStore) -> bool:
    """Идемпотентное повышение схемы FabricStore с v1 до v2.

    Возвращает True, если схема была обновлена, False - если уже v2.
    """
    if not isinstance(store, FabricStore):
        raise FabricError("Некорректный экземпляр FabricStore")

    with store.atomic():
        version_row = store.db.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        current_version = version_row[0] if version_row else "1"

        if current_version == "2":
            # Проверяем наличие всех необходимых таблиц
            required = ("effect_intents", "effect_operations", "effect_receipts")
            for table in required:
                if not store.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone():
                    raise FabricError(f"Схема v2 повреждена: отсутствует таблица {table}")
            return False

        if current_version != "1":
            raise FabricError(f"Неподдерживаемая версия схемы: {current_version}")

        # 1. effect_intents: хранение намерений внешнего эффекта до исполнения
        store.db.execute("""
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
            )
        """)
        store.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_effect_intents_host ON effect_intents(host_id, target_id)"
        )

        # 2. effect_operations: журнал операций фазового выполнения
        store.db.execute("""
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
            )
        """)
        store.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_effect_task ON effect_operations(task_id, phase)"
        )

        # 3. effect_receipts: неизменяемые проверенные квитанции эффекта
        store.db.execute("""
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
            )
        """)

        # 4. Триггеры неизменяемости квитанций
        for operation in ("UPDATE", "DELETE"):
            trigger_name = f"immutable_effect_receipt_{operation.lower()}"
            store.db.execute(
                f"CREATE TRIGGER IF NOT EXISTS {trigger_name} "
                f"BEFORE {operation} ON effect_receipts "
                f"BEGIN SELECT RAISE(ABORT, 'EFFECT_RECEIPT_IMMUTABLE'); END;"
            )

        # 5. Обновление метаданных
        store.db.execute("UPDATE meta SET value='2' WHERE key='schema_version'")

    return True
