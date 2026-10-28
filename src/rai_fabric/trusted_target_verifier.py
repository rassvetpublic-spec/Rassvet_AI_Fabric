"""Доверенные верификаторы мандата владельца и целевого эффекта (L3 / W2).

Реализует fail-closed проверку для verify_effect_receipt():
1. LocalTrustedGrantRegistry - проверка мандата против локального доверенного хранилища.
2. LocalTargetReadbackVerifier - криптографический readback целевого эффекта.
"""
from __future__ import annotations

__version__ = "1.0.0"

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

    def register_target_root(self, target_id: str, root_path: Path) -> None:
        self._target_roots[target_id] = Path(root_path).resolve()

    def register_synthetic_sink(self, target_id: str, sink_store: dict[str, str]) -> None:
        self._synthetic_sinks[target_id] = sink_store

    def verify_target(self, intent: EffectIntent, receipt: TargetEffectReceipt) -> Optional[VerifiedReadback]:
        """Криптографический readback целевого эффекта."""
        if not isinstance(intent, EffectIntent) or not isinstance(receipt, TargetEffectReceipt):
            return None
        if intent.host_id != self.expected_host_id or receipt.host_id != self.expected_host_id:
            return None

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
                target_revision=receipt.target_revision,
                content_sha256=actual_sha,
                verifier_ref=self.verifier_ref,
            )

        # 2. Файловый root target
        if intent.target_id in self._target_roots:
            root = self._target_roots[intent.target_id]
            # operation_id используется как относительный путь или идентификатор файла
            target_file = (root / receipt.operation_id).resolve()
            # Защита от path traversal
            if not target_file.is_relative_to(root):
                return None
            if not target_file.is_file():
                return None
            data = target_file.read_bytes()
            actual_sha = hashlib.sha256(data).hexdigest()
            return VerifiedReadback(
                target_id=intent.target_id,
                host_id=self.expected_host_id,
                target_revision=receipt.target_revision,
                content_sha256=actual_sha,
                verifier_ref=self.verifier_ref,
            )

        return None
