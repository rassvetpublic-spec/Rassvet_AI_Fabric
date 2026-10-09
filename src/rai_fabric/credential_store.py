"""Атомарное хранение проверенной OAuth-сессии под DPAPI текущего Windows SID.

Модуль не вызывает OAuth и не запрашивает модели. Тестовый backend приватный:
в production-конструкторе всегда используются WindowsUserDPAPI и WindowsVaultACL.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any

from .oauth_identity import ISSUER, VerifiedIdentity
from .windows_vault import (VaultError, WindowsUserDPAPI, credential_record_key,
                            default_vault_root)

_MAX_PLAINTEXT = 512 * 1024
_MAX_CIPHERTEXT = 4 * 1024 * 1024
_SCHEMA = "RAI_FABRIC_OAUTH_CREDENTIAL/1"
_FIELDS = frozenset({"issuer", "client_id", "subject", "access_token", "refresh_token",
                     "id_token", "token_type", "scopes", "ext_agent_host_id", "saved_at",
                     "expires_at"})
_REVISION = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True, repr=False)
class LoadedCredential:
    """Приватные данные. Нельзя выводить credentials в лог или checkpoint."""
    revision: str
    credentials: Mapping[str, Any]

    def __repr__(self) -> str:
        return "LoadedCredential(данные скрыты)"


def _validate_credential(identity: VerifiedIdentity, value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(identity, VerifiedIdentity) or not isinstance(value, Mapping):
        raise VaultError("Не передана подтверждённая учётная запись")
    if set(value) != _FIELDS:
        raise VaultError("Неполная или неизвестная схема записи OAuth")
    if (identity.issuer != ISSUER or value.get("issuer") != ISSUER
            or value.get("client_id") != identity.client_id
            or value.get("subject") != identity.subject
            or value.get("token_type") != "Bearer"):
        raise VaultError("Запись OAuth не соответствует проверенной личности")
    for field in ("access_token", "refresh_token", "id_token"):
        token = value[field]
        if not isinstance(token, str) or not 16 <= len(token) <= 131072:
            raise VaultError("Неверный формат зашифровываемых данных")
    scopes = value.get("scopes")
    if (not isinstance(scopes, list) or len(scopes) > 20
            or not all(isinstance(scope, str) and 1 <= len(scope) <= 128
                       and not any(c.isspace() for c in scope) for scope in scopes)
            or len(set(scopes)) != len(scopes)):
        raise VaultError("Некорректный список разрешений")
    host_id = value.get("ext_agent_host_id")
    if not isinstance(host_id, str) or not host_id.startswith("urn:uuid:"):
        raise VaultError("Неподдерживаемый идентификатор агентной машины")
    try:
        if str(uuid.UUID(host_id[9:])) != host_id[9:] or uuid.UUID(host_id[9:]).version != 4:
            raise ValueError("Неверная версия UUID")
    except (ValueError, AttributeError):
        raise VaultError("Неверный UUID идентификатора агентной машины") from None
    if (type(value.get("saved_at")) is not int or type(value.get("expires_at")) is not int
            or value["saved_at"] < 0 or value["expires_at"] <= value["saved_at"]):
        raise VaultError("Некорректный период действия токена")
    return dict(value)


def _parse_envelope(data: bytes, identity: VerifiedIdentity) -> LoadedCredential:
    if not isinstance(data, bytes) or not 2 <= len(data) <= _MAX_PLAINTEXT:
        raise VaultError("Некорректный размер защищённой записи")

    def unique(items):
        out = {}
        for name, value in items:
            if name in out:
                raise VaultError("Повторяющееся поле защищённой записи")
            out[name] = value
        return out

    try:
        item = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (TypeError, ValueError, UnicodeError):
        raise VaultError("Повреждён формат защищённой записи") from None
    if not isinstance(item, dict) or set(item) != {"schema", "revision", "credentials"}:
        raise VaultError("Неизвестная версия защищённой записи")
    if item["schema"] != _SCHEMA or not isinstance(item["revision"], str) \
            or not _REVISION.fullmatch(item["revision"]):
        raise VaultError("Повреждён идентификатор версии записи")
    return LoadedCredential(revision=item["revision"],
                            credentials=_validate_credential(identity, item["credentials"]))


class _AtomicVaultStore:
    """Только внутреннее тестируемое ядро. Production создаётся через WindowsCredentialVault."""

    def __init__(self, root: Path, protector: Any, guard: Any):
        self._root = Path(root)
        self._protector = protector
        self._guard = guard

    def _ensure_root(self) -> None:
        base = self._root.parent
        self._guard.reject_reparse(base)
        if not base.exists():
            try:
                base.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                pass
        self._guard.reject_reparse(self._root)
        if not self._root.exists():
            try:
                self._root.mkdir(mode=0o700)
            except FileExistsError:
                pass
            else:
                self._guard.restrict(self._root)
        if not self._root.is_dir():
            raise VaultError("Защищённое хранилище не является каталогом")
        self._guard.verify(self._root)

    def _path(self, identity: VerifiedIdentity) -> Path:
        if not isinstance(identity, VerifiedIdentity):
            raise VaultError("Требуется подтверждённая личность")
        record_name = credential_record_key(client_id=identity.client_id,
                                            subject=identity.subject,
                                            issuer=identity.issuer)
        return self._root / (record_name + ".dpapi")

    def _read(self, path: Path, identity: VerifiedIdentity) -> LoadedCredential:
        self._guard.reject_reparse(path)
        self._guard.verify(path)
        try:
            with path.open("rb") as f:
                body = f.read(_MAX_CIPHERTEXT + 1)
        except OSError:
            raise VaultError("Не удалось прочитать защищённую запись") from None
        if not 1 <= len(body) <= _MAX_CIPHERTEXT:
            raise VaultError("Неверный размер зашифрованной записи")
        plaintext = self._protector.unprotect(body)
        return _parse_envelope(plaintext, identity)

    def load(self, identity: VerifiedIdentity) -> LoadedCredential:
        """Расшифровка в памяти при совпадении подтверждённой личности."""
        self._ensure_root()
        path = self._path(identity)
        if not path.exists():
            raise VaultError("Учётная запись отсутствует в хранилище")
        return self._read(path, identity)

    def save(self, identity: VerifiedIdentity, credential: Mapping[str, Any],
             *, expected_revision: str | None = None) -> str:
        """Начальная запись либо CAS-замена с поколением (refresh rotation)."""
        values = _validate_credential(identity, credential)
        if expected_revision is not None and (not isinstance(expected_revision, str)
                                               or not _REVISION.fullmatch(expected_revision)):
            raise VaultError("Некорректная предыдущая ревизия")
        self._ensure_root()
        path = self._path(identity)
        lock = self._root / (path.stem + ".lock")
        self._guard.reject_reparse(lock)
        try:
            lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise VaultError("Запись уже изменяется другим процессом; повтор запрещён") from None
        except OSError:
            raise VaultError("Невозможно заблокировать защищённую запись") from None
        try:
            os.close(lock_fd)
            self._guard.restrict(lock)
            if path.exists():
                previous = self._read(path, identity)
                if expected_revision is None or previous.revision != expected_revision:
                    raise VaultError("Ревизия записи изменилась; обновление запрещено")
            elif expected_revision is not None:
                raise VaultError("Исходная ревизия записи отсутствует")
            self._guard.reject_reparse(path)
            revision = uuid.uuid4().hex
            envelope = {"schema": _SCHEMA, "revision": revision, "credentials": values}
            plaintext = json.dumps(envelope, ensure_ascii=False,
                                   separators=(",", ":"), sort_keys=True).encode("utf-8")
            if len(plaintext) > _MAX_PLAINTEXT:
                raise VaultError("Запись OAuth превышает допустимый размер")
            encrypted = self._protector.protect(plaintext)
            if not isinstance(encrypted, bytes) or not 1 <= len(encrypted) <= _MAX_CIPHERTEXT:
                raise VaultError("Неверный размер результата шифрования")
            temp = self._root / (path.stem + "." + uuid.uuid4().hex + ".tmp")
            try:
                fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
                try:
                    self._guard.restrict(temp)  # до записи ciphertext
                    with os.fdopen(fd, "wb") as handle:
                        fd = -1
                        handle.write(encrypted)
                        handle.flush()
                        os.fsync(handle.fileno())
                finally:
                    if fd != -1:
                        os.close(fd)
                self._guard.reject_reparse(path)
                os.replace(temp, path)
                self._guard.verify(path)
            finally:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
            return revision
        except VaultError:
            raise
        except OSError:
            raise VaultError("Не удалось атомарно сохранить защищённую запись") from None
        finally:
            try:
                lock.unlink(missing_ok=True)
            except OSError:
                # Блокировка после ошибки требует ручной диагностики.
                pass


class WindowsCredentialVault(_AtomicVaultStore):
    """Производственное хранилище. Нельзя заменить protector или ACL из API."""

    def __init__(self, *, root: Path | None = None):
        if os.name != "nt":
            raise VaultError("Учётные данные поддерживаются только на Windows")
        from .windows_acl import WindowsVaultACL
        default = default_vault_root()
        requested = Path(root) if root is not None else default
        # Выделенный суффикс используется только для интеграционных тестов.
        if (requested != default and not (requested.parent == default.parent
                                            and requested.name.startswith("oauth_v1_test_")
                                            and re.fullmatch(r"oauth_v1_test_[0-9a-f]{32}", requested.name))):
            raise VaultError("Путь хранилища не принадлежит разрешённой зоне Windows")
        super().__init__(requested, WindowsUserDPAPI(), WindowsVaultACL())
