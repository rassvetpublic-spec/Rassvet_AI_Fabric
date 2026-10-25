"""Доверенные верификаторы мандата владельца и целевого эффекта (L3 / W2).

Реализует fail-closed проверку для verify_effect_receipt():
1. LocalTrustedGrantRegistry - проверка мандата против локального доверенного хранилища.
2. LocalTargetReadbackVerifier - криптографический readback целевого эффекта.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .effect_receipt_contract import EffectIntent, TargetEffectReceipt, VerifiedReadback


class VerifierError(Exception):
    """Ошибка верификации эффекта или мандата."""


@dataclass(frozen=True)
class PinnedGrant:
    grant_ref: str
    task_id: str
    host_id: str
    target_id: str
    deadline_utc: float


class LocalTrustedGrantRegistry:
    """Локальный реестр мандатов владельца хоста (MTD 011011).

    Мандат должен быть проверен локально, а не доверяться утверждению из сообщения.
    """

    def __init__(self, expected_host_id: str = "RASSVET_DESKTOP"):
        self.expected_host_id = expected_host_id
        self._grants: dict[str, PinnedGrant] = {}

    def register_grant(
        self,
        grant_ref: str,
        task_id: str,
        target_id: str,
        deadline_utc: float,
        host_id: Optional[str] = None,
    ) -> None:
        hid = host_id or self.expected_host_id
        self._grants[grant_ref] = PinnedGrant(
            grant_ref=grant_ref,
            task_id=task_id,
            host_id=hid,
            target_id=target_id,
            deadline_utc=deadline_utc,
        )

    def revoke_grant(self, grant_ref: str) -> None:
        self._grants.pop(grant_ref, None)

    def authorize(self, intent: EffectIntent) -> bool:
        """Валидация мандата в момент поступления квитанции."""
        if not isinstance(intent, EffectIntent):
            return False
        grant = self._grants.get(intent.owner_grant_ref)
        if grant is None:
            return False
        if grant.task_id != intent.task_id:
            return False
        if grant.host_id != intent.host_id or grant.host_id != self.expected_host_id:
            return False
        if grant.target_id != intent.target_id:
            return False
        if grant.deadline_utc < intent.lease_deadline_utc:
            return False
        return True


class LocalTargetReadbackVerifier:
    """Независимый верификатор целевого состояния хоста.

    Выполняет прямое чтение (CAS/FS/SQLite/Git) и рассчитывает content_sha256.
    Никогда не доверяет заголовкам L2 конверта или TransportMessageEnvelope.digest_sha256.
    """

    def __init__(self, expected_host_id: str = "RASSVET_DESKTOP", verifier_ref: str = "local-fs-cas-verifier-v1"):
        self.expected_host_id = expected_host_id
        self.verifier_ref = verifier_ref
        self._target_roots: dict[str, Path] = {}
        self._synthetic_sinks: dict[str, dict[str, str]] = {}
        self._target_revisions: dict[Any, str] = {}

    def register_target_root(self, target_id: str, root_path: Path) -> None:
        self._target_roots[target_id] = Path(root_path).resolve()

    def register_synthetic_sink(self, target_id: str, sink_store: dict[str, str]) -> None:
        self._synthetic_sinks[target_id] = sink_store

    def register_target_revision(self, target_id: str, revision: str, operation_id: Optional[str] = None) -> None:
        if operation_id:
            self._target_revisions[(target_id, operation_id)] = revision
        else:
            self._target_revisions[target_id] = revision

    def verify_target(self, intent: EffectIntent, receipt: TargetEffectReceipt) -> Optional[VerifiedReadback]:
        """Криптографический readback целевого эффекта."""
        if not isinstance(intent, EffectIntent) or not isinstance(receipt, TargetEffectReceipt):
            return None
        if intent.host_id != self.expected_host_id or receipt.host_id != self.expected_host_id:
            return None
        if intent.operation_id != receipt.operation_id or intent.target_id != receipt.target_id:
            return None

        # Отклоняем невалидные, пустые или явно непроверенные ревизии (fail-closed)
        if not receipt.target_revision or "UNVERIFIED" in receipt.target_revision.upper():
            return None

        # Проверка зарегистрированной доверенной ревизии, если задана для цели/операции
        expected_rev = self._target_revisions.get((intent.target_id, receipt.operation_id)) or self._target_revisions.get(intent.target_id)
        if expected_rev is not None and receipt.target_revision != expected_rev:
            return None
        effective_rev = expected_rev if expected_rev is not None else receipt.target_revision

        # 1. Синтетический/тестовый sink
        if intent.target_id in self._synthetic_sinks:
            sink = self._synthetic_sinks[intent.target_id]
            content = sink.get(receipt.operation_id)
            if content is None:
                return None
            actual_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
            return VerifiedReadback(
                target_id=intent.target_id,
                host_id=self.expected_host_id,
                target_revision=effective_rev,
                content_sha256=actual_sha,
                verifier_ref=self.verifier_ref,
            )

        # 2. Файловый root target
        if intent.target_id in self._target_roots:
            root = self._target_roots[intent.target_id].resolve()
            op_id = receipt.operation_id
            # Защита от path traversal, ADS (:), null bytes, абсолютных путей
            if ":" in op_id or "\0" in op_id:
                return None
            try:
                op_path = Path(op_id)
                if op_path.is_absolute():
                    return None
                target_file = (root / op_path).resolve()
                if not target_file.is_relative_to(root) or target_file == root:
                    return None
                if target_file.is_symlink():
                    return None
                parent = target_file.parent
                while parent != root and parent != parent.parent:
                    if parent.is_symlink():
                        return None
                    parent = parent.parent
            except (ValueError, RuntimeError):
                return None

            if not target_file.is_file():
                return None
            data = target_file.read_bytes()
            actual_sha = hashlib.sha256(data).hexdigest()
            return VerifiedReadback(
                target_id=intent.target_id,
                host_id=self.expected_host_id,
                target_revision=effective_rev,
                content_sha256=actual_sha,
                verifier_ref=self.verifier_ref,
            )

        return None
