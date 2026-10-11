"""Заготовка защищённого Windows-хранилища: текущий пользователь DPAPI.

Реализованы только защита/раскрытие отдельных BLOB и план пути. Файлы с
настоящими OAuth-токенами здесь намеренно НЕ создаются. Хранение, ACL,
синхронизация refresh-замены и авторизация требуют отдельной приёмки.
"""
from __future__ import annotations

__version__ = "1.0.0"

import ctypes
import hashlib
import os
from ctypes import wintypes
from pathlib import Path

from .oauth_identity import ISSUER
from .store import FabricError


class VaultError(FabricError):
    """Сбой защищённого хранилища; секреты не включаются в сообщение."""


# Cтруктура Windows DATA_BLOB (Wincrypt.h).
class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


_MAX_BLOB = 1024 * 1024
_APP_ENTROPY = b"RASSVET_AI_FABRIC_USER_DPAPI_V1"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


def credential_record_key(*, client_id: str, subject: str, issuer: str = ISSUER) -> str:
    """Обезличенное имя записи; не выводит почту, subject или OAuth-токены."""
    if (issuer != ISSUER or not isinstance(client_id, str)
            or not client_id or client_id == "dynamic_agent_client"
            or not isinstance(subject, str) or not subject
            or len(client_id) > 256 or len(subject) > 512):
        raise VaultError("Невозможно назначить имя непроверенной учётной записи")
    raw = "\0".join((issuer, client_id, subject)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def default_vault_root(*, local_appdata: str | None = None) -> Path:
    """Только рассчитывает путь под профилем Windows; ничего не создаёт."""
    if os.name != "nt":
        raise VaultError("Защищённое хранилище поддерживается только в Windows")
    raw = local_appdata if local_appdata is not None else os.environ.get("LOCALAPPDATA")
    if not isinstance(raw, str) or not raw.strip():
        raise VaultError("Не найдена системная папка LOCALAPPDATA")
    home = Path(raw)
    if not home.is_absolute():
        raise VaultError("Путь профиля должен быть абсолютным")
    return home / "Rassvet_AI_Fabric" / "oauth_v1"


class WindowsUserDPAPI:
    """Шифрование DPAPI текущего пользователя; без режима LOCAL_MACHINE."""

    def __init__(self):
        if os.name != "nt":
            raise VaultError("DPAPI доступен только под Windows")
        self._crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        args = [ctypes.POINTER(_DataBlob), ctypes.c_wchar_p,
                ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                wintypes.DWORD, ctypes.POINTER(_DataBlob)]
        self._crypt.CryptProtectData.argtypes = args
        self._crypt.CryptProtectData.restype = wintypes.BOOL
        self._crypt.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        self._crypt.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel.LocalFree.restype = ctypes.c_void_p

    @staticmethod
    def _as_blob(payload: bytes) -> tuple[_DataBlob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(payload)
        return (_DataBlob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer)

    def _transform(self, value: bytes, *, protect: bool) -> bytes:
        if not isinstance(value, bytes) or not 1 <= len(value) <= _MAX_BLOB:
            raise VaultError("Размер BLOB за пределами разрешённого диапазона")
        input_blob, input_buffer = self._as_blob(value)
        entropy_blob, entropy_buffer = self._as_blob(_APP_ENTROPY)
        output = _DataBlob()
        result = b""
        try:
            if protect:
                ok = self._crypt.CryptProtectData(
                    ctypes.byref(input_blob), None, ctypes.byref(entropy_blob),
                    None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output),
                )
            else:
                ok = self._crypt.CryptUnprotectData(
                    ctypes.byref(input_blob), None, ctypes.byref(entropy_blob),
                    None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output),
                )
            if not ok:
                raise VaultError(f"DPAPI отказал в операции (Win32: {ctypes.get_last_error()})")
            if output.cbData > _MAX_BLOB * 4:
                raise VaultError("Размер результата DPAPI превышает ограничение")
            result = ctypes.string_at(output.pbData, output.cbData)
            return result
        finally:
            if output.pbData:
                if not protect and output.cbData:
                    ctypes.memset(output.pbData, 0, output.cbData)
                self._kernel.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))
            ctypes.memset(ctypes.addressof(input_buffer), 0, len(input_buffer))
            ctypes.memset(ctypes.addressof(entropy_buffer), 0, len(entropy_buffer))

    def protect(self, plaintext: bytes) -> bytes:
        """Шифрует данные пользователя; запрещён режим шифрования всей машины."""
        return self._transform(plaintext, protect=True)

    def unprotect(self, encrypted: bytes) -> bytes:
        """Расшифровывает только при наличии исходного контекста пользователя."""
        return self._transform(encrypted, protect=False)
