"""Windows Credential Manager adapter for RAiF-owned generic credentials.

This module does not touch the native Antigravity credential target, IDE files
or any running process. No credentials are displayed or written to GitHub.
"""
from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes

_TARGET_PREFIX = "RAiF_AG_Supervisor:account:"
_ACCOUNT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_CRED_MAX_BLOB_SIZE = 2560
_NOT_FOUND = 1168


class CredentialVaultError(RuntimeError):
    """Sanitized native error; contains no token or account information."""


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_PCREDENTIALW = ctypes.POINTER(_CREDENTIALW)


def _target(account_id: str) -> str:
    if not isinstance(account_id, str) or not _ACCOUNT_ID.fullmatch(account_id):
        raise ValueError("invalid account ID")
    return _TARGET_PREFIX + account_id


class WindowsCredentialVault:
    """Store credentials under RAiF-specific targets for the current Windows user.

    API exposes existence, insert and deletion only. Reading secrets back and
    modifying Antigravity's own credential are deliberately out of scope.
    Windows protects generic credentials for the signed-in account; elevated
    processes or account compromise may still expose their contents.
    """

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows Credential Manager is available only on Windows")
        self._api = ctypes.WinDLL("advapi32", use_last_error=True)

        self._api.CredWriteW.argtypes = (_PCREDENTIALW, wintypes.DWORD)
        self._api.CredWriteW.restype = wintypes.BOOL
        self._api.CredReadW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(_PCREDENTIALW),
        )
        self._api.CredReadW.restype = wintypes.BOOL
        self._api.CredDeleteW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        )
        self._api.CredDeleteW.restype = wintypes.BOOL
        self._api.CredFree.argtypes = (ctypes.c_void_p,)
        self._api.CredFree.restype = None

    @staticmethod
    def _error(action: str) -> CredentialVaultError:
        code = ctypes.get_last_error()
        return CredentialVaultError(f"Credential Manager {action} failed ({code})")

    def put(self, account_id: str, secret: str) -> None:
        target = _target(account_id)
        if not isinstance(secret, str) or not secret:
            raise ValueError("invalid credential value")
        raw = secret.encode("utf-8")
        if len(raw) > _CRED_MAX_BLOB_SIZE:
            raise ValueError("credential too large for Windows Credential Manager")
        # ctypes owns the native write buffer; best effort zero before release.
        buffer = ctypes.create_string_buffer(raw, len(raw))
        try:
            entry = _CREDENTIALW()
            entry.Type = _CRED_TYPE_GENERIC
            entry.TargetName = target
            entry.UserName = "RAiF_AG_Supervisor"
            entry.CredentialBlobSize = len(raw)
            entry.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            entry.Persist = _CRED_PERSIST_LOCAL_MACHINE
            if not self._api.CredWriteW(ctypes.byref(entry), 0):
                raise self._error("write")
        finally:
            ctypes.memset(buffer, 0, len(raw))
            # Python str/bytes are immutable: their memory cannot be wiped here.
            del raw

    def has(self, account_id: str) -> bool:
        target = _target(account_id)
        pointer = _PCREDENTIALW()
        if not self._api.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            code = ctypes.get_last_error()
            if code == _NOT_FOUND:
                return False
            raise self._error("read")
        try:
            return True
        finally:
            self._api.CredFree(ctypes.cast(pointer, ctypes.c_void_p))

    def delete(self, account_id: str) -> None:
        target = _target(account_id)
        if not self._api.CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
            code = ctypes.get_last_error()
            if code != _NOT_FOUND:
                raise self._error("delete")

    def __repr__(self) -> str:
        return "WindowsCredentialVault(redacted)"
