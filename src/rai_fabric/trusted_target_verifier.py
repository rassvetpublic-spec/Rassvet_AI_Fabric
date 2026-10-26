"""Доверенные верификаторы мандата владельца и целевого эффекта (L3 / W2).

Реализует fail-closed проверку для verify_effect_receipt():
1. LocalTrustedGrantRegistry - проверка мандата против локального доверенного хранилища.
2. LocalTargetReadbackVerifier - криптографический readback целевого эффекта.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from .effect_receipt_contract import EffectIntent, TargetEffectReceipt, VerifiedReadback


class VerifierError(Exception):
    """Ошибка верификации эффекта или мандата."""


ALLOWED_MANDATE_SCOPES = frozenset({
    "OWNER_AUTHORIZED_FINAL_PASS",
    "EVIDENCE_ADMISSIBLE_ONLY",
})


@dataclass(frozen=True)
class PinnedGrant:
    grant_ref: str
    task_id: str
    host_id: str
    target_id: str
    deadline_utc: float
    signature: str = ""
    mandate_scope: str = "EVIDENCE_ADMISSIBLE_ONLY"
    provider: str = "antigravity"


ALLOWED_OWNER_GRANT_PROVIDERS = frozenset({"antigravity", "codex-app"})


def _grant_payload_bytes(grant: PinnedGrant) -> bytes:
    """Versioned, unambiguous signing payload (no colon-delimited field collisions).

    This is a local Python encoding contract, NOT RFC8785/JCS or host attestation.
    Legacy colon-separated signatures must never be silently accepted.
    """
    return json.dumps({
        "schema": "RAIF_PINNED_GRANT/2",
        "grant_ref": grant.grant_ref,
        "task_id": grant.task_id,
        "host_id": grant.host_id,
        "target_id": grant.target_id,
        "deadline_utc": grant.deadline_utc,
        "mandate_scope": grant.mandate_scope,
        "provider": grant.provider,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class OwnerGrantSigner:
    """Защищённый эмитент мандатов владельца (MTD 011011).

    Работает вне локального непроверенного реестра, криптографически подписывая мандаты секретным ключом владельца.
    """

    def __init__(self, owner_private_key: bytes, host_id: str = "RASSVET_DESKTOP"):
        if not owner_private_key or len(owner_private_key) < 16:
            raise ValueError("OWNER_KEY_TOO_SHORT: Owner signing key must be at least 16 bytes")
        self._private_key = owner_private_key
        self.host_id = host_id

    def issue_grant(
        self,
        grant_ref: str,
        task_id: str,
        target_id: str,
        deadline_utc: float,
        host_id: Optional[str] = None,
        mandate_scope: str = "EVIDENCE_ADMISSIBLE_ONLY",
        provider: str = "antigravity",
    ) -> PinnedGrant:
        if not isinstance(provider, str) or provider not in ALLOWED_OWNER_GRANT_PROVIDERS:
            raise VerifierError(f"UNAUTHORIZED_OWNER_GRANT_PROVIDER: {provider}")
        if type(deadline_utc) not in (int, float) or not math.isfinite(deadline_utc):
            raise VerifierError("INVALID_OWNER_GRANT_DEADLINE")
        if not isinstance(mandate_scope, str) or mandate_scope not in ALLOWED_MANDATE_SCOPES:
            raise VerifierError(f"UNAUTHORIZED_MANDATE_SCOPE: {mandate_scope}")
        hid = host_id or self.host_id
        unsigned = PinnedGrant(
            grant_ref=grant_ref,
            task_id=task_id,
            host_id=hid,
            target_id=target_id,
            deadline_utc=deadline_utc,
            mandate_scope=mandate_scope,
            provider=provider,
        )
        sig = hmac.new(self._private_key, _grant_payload_bytes(unsigned), hashlib.sha256).hexdigest()
        return replace(unsigned, signature=sig)


DEFAULT_SIGNING_KEY = b"rassvet-desktop-default-signing-key"


class LocalTrustedGrantRegistry:
    """Локальный проверяющий реестр мандатов владельца хоста (MTD 011011).

    Реестр является STRICTLY VERIFYING-ONLY (только проверка и импорт подписанных мандатов).
    Локальная эмиссия/генерация подписи внутри реестра исключена.
    Все мандаты создаются внешним защищённым OwnerGrantSigner и регистрируются через register_signed_grant.
    Использование публичного дефолтного ключа на путях реальных провайдеров запрещено.
    """

    def __init__(
        self,
        expected_host_id: str = "RASSVET_DESKTOP",
        owner_verifying_key: bytes | None = None,
        signing_key: bytes | None = None,
    ):
        self.expected_host_id = expected_host_id
        key = owner_verifying_key or signing_key
        if key is None:
            self._verifying_key = DEFAULT_SIGNING_KEY
            self.is_default_key = True
        else:
            self._verifying_key = key
            self.is_default_key = (key == DEFAULT_SIGNING_KEY)
        self._grants: dict[str, PinnedGrant] = {}

    def register_signed_grant(self, grant: PinnedGrant) -> None:
        """Регистрация мандата, уже подписанного независимым владельцем (единственный путь импорта)."""
        if not isinstance(grant, PinnedGrant):
            raise VerifierError("INVALID_GRANT_TYPE")
        if not self._verify_grant(grant):
            raise VerifierError("INVALID_OWNER_GRANT_SIGNATURE")
        self._grants[grant.grant_ref] = grant

    def register_grant(self, *args, **kwargs) -> None:
        """Запрещено: реестр является строго verifying-only, не имеет права выпускать подписи."""
        raise VerifierError("LOCAL_MINTING_FORBIDDEN: LocalTrustedGrantRegistry is verifying-only. Use OwnerGrantSigner.issue_grant() and register_signed_grant()")

    def revoke_grant(self, grant_ref: str) -> None:
        self._grants.pop(grant_ref, None)

    def get_grant(self, grant_ref: str) -> Optional[PinnedGrant]:
        return self._grants.get(grant_ref)

    def _verify_grant(self, grant: PinnedGrant) -> bool:
        # Fail closed for malformed/unhashable values before cryptographic verification.
        try:
            if not isinstance(grant.mandate_scope, str) or grant.mandate_scope not in ALLOWED_MANDATE_SCOPES:
                return False
            if not isinstance(grant.provider, str) or grant.provider not in ALLOWED_OWNER_GRANT_PROVIDERS:
                return False
            if type(grant.deadline_utc) not in (float, int) or not math.isfinite(grant.deadline_utc):
                return False
            expected_sig = hmac.new(
                self._verifying_key, _grant_payload_bytes(grant), hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(grant.signature, expected_sig)
        except (TypeError, ValueError, OverflowError, UnicodeError):
            return False

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
        if grant.provider != intent.provider:
            return False
        try:
            if grant.deadline_utc < intent.lease_deadline_utc:
                return False
        except (TypeError, ValueError, OverflowError):
            return False
        return self._verify_grant(grant)


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

        # Проверка зарегистрированной доверенной ревизии (fail-closed если ревизия не подтверждена)
        expected_rev = self._target_revisions.get((intent.target_id, receipt.operation_id)) or self._target_revisions.get(intent.target_id)
        if expected_rev is None:
            # Ревизия не зарегистрирована независимым доверенным источником -> fail-closed
            return None
        if receipt.target_revision != expected_rev:
            return None
        effective_rev = expected_rev

        # 1. Синтетический/тестовый sink допускается только для offline mock.
        # Для реального провайдера нельзя подменять файловый readback данными fixture,
        # даже когда для того же target_id одновременно зарегистрированы root и sink.
        # Реальный путь ниже читает исключительно разрешённый файловый root.
        if intent.provider in ("mock", "codex-mock") and intent.target_id in self._synthetic_sinks:
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
