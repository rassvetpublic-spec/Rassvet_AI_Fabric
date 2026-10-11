"""Windows DACL текущего пользователя и проверка reparse points для vault.

Защита каталога и файла осуществляется до записи шифротекста.
Имя пользователя и SID не включаются в сообщения и журналы.
"""
from __future__ import annotations

__version__ = "1.0.0"

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from .windows_vault import VaultError

_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_SE_DACL_PROTECTED = 0x1000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_ACL_SIZE_INFORMATION = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_FILE_ALL_ACCESS = 0x1F01FF


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [("AceCount", wintypes.DWORD),
                ("AclBytesInUse", wintypes.DWORD),
                ("AclBytesFree", wintypes.DWORD)]


class _AceHeader(ctypes.Structure):
    _fields_ = [("AceType", ctypes.c_ubyte),
                ("AceFlags", ctypes.c_ubyte),
                ("AceSize", wintypes.WORD),
                ("Mask", wintypes.DWORD)]


class WindowsVaultACL:
    """Владелец имеет один разрешающий DACL ACE; наследование отключено.

    Не защищает от другого процесса, работающего под *тем же* Windows SID.
    """

    def __init__(self):
        if os.name != "nt":
            raise VaultError("Контроль NTFS ACL поддерживается только Windows")
        self._api = ctypes.WinDLL("advapi32", use_last_error=True)
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure()
        self._sid = self._current_sid()

    def _configure(self):
        a, k = self._api, self._kernel
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
        k.GetFileAttributesW.restype = wintypes.DWORD
        k.LocalFree.argtypes = [ctypes.c_void_p]
        k.LocalFree.restype = ctypes.c_void_p
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        a.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        a.OpenProcessToken.restype = wintypes.BOOL
        a.GetTokenInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                           ctypes.c_void_p, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD)]
        a.GetTokenInformation.restype = wintypes.BOOL
        a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        a.ConvertSidToStringSidW.restype = wintypes.BOOL
        a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD)]
        a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        a.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                                               ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
        a.GetSecurityDescriptorDacl.restype = wintypes.BOOL
        a.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                                             ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_void_p]
        a.SetNamedSecurityInfoW.restype = wintypes.DWORD
        a.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                                             ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                             ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                             ctypes.POINTER(ctypes.c_void_p)]
        a.GetNamedSecurityInfoW.restype = wintypes.DWORD
        a.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p,
                                                    ctypes.POINTER(wintypes.WORD),
                                                    ctypes.POINTER(wintypes.DWORD)]
        a.GetSecurityDescriptorControl.restype = wintypes.BOOL
        a.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        wintypes.DWORD, wintypes.DWORD]
        a.GetAclInformation.restype = wintypes.BOOL
        a.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(ctypes.c_void_p)]
        a.GetAce.restype = wintypes.BOOL
        a.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        a.EqualSid.restype = wintypes.BOOL
        a.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR,
                                             ctypes.POINTER(ctypes.c_void_p)]
        a.ConvertStringSidToSidW.restype = wintypes.BOOL

    def _current_sid(self) -> str:
        token = wintypes.HANDLE()
        if not self._api.OpenProcessToken(self._kernel.GetCurrentProcess(), _TOKEN_QUERY,
                                          ctypes.byref(token)):
            raise VaultError("Не удалось прочитать идентификатор Windows")
        try:
            size = wintypes.DWORD(0)
            self._api.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
            if not 16 <= size.value <= 65536:
                raise VaultError("Некорректные данные Windows SID")
            buffer = ctypes.create_string_buffer(size.value)
            if not self._api.GetTokenInformation(token, _TOKEN_USER, buffer,
                                                 size.value, ctypes.byref(size)):
                raise VaultError("Не удалось проверить Windows SID")
            sid = ctypes.cast(buffer, ctypes.POINTER(_SidAndAttributes)).contents.Sid
            sid_string = ctypes.c_wchar_p()
            if not self._api.ConvertSidToStringSidW(sid, ctypes.byref(sid_string)):
                raise VaultError("Не удалось сформировать Windows SID")
            try:
                result = sid_string.value
            finally:
                self._kernel.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p))
            if not result or not result.startswith("S-1-"):
                raise VaultError("Некорректный SID текущего пользователя")
            return result
        finally:
            self._kernel.CloseHandle(token)

    def reject_reparse(self, path: Path, *, required: bool = False) -> None:
        """Проверяет путь и всех существующих родителей, включая junction."""
        path = Path(path)
        if not path.is_absolute() or str(path).startswith("\\\\"):
            raise VaultError("Хранилище должно быть на локальном диске Windows")
        chain = list(reversed((path, *path.parents)))
        for component in chain:
            attribute = self._kernel.GetFileAttributesW(str(component))
            if attribute == _INVALID_FILE_ATTRIBUTES:
                if ctypes.get_last_error() not in (2, 3):
                    raise VaultError("Невозможно безопасно проверить компонент пути")
                if required and component == path:
                    raise VaultError("Путь защищённого хранилища не найден")
                continue
            if attribute & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise VaultError("Символическая ссылка или junction в пути запрещены")

    def restrict(self, path: Path) -> None:
        """Применяет защищённую ACL и немедленно проверяет результат."""
        self.reject_reparse(path, required=True)
        sec_desc = ctypes.c_void_p()
        sddl = f"D:P(A;;FA;;;{self._sid})"
        if not self._api.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(sec_desc), None):
            raise VaultError("Не удалось подготовить изолированную ACL")
        try:
            present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
            if not self._api.GetSecurityDescriptorDacl(
                    sec_desc, ctypes.byref(present), ctypes.byref(dacl),
                    ctypes.byref(defaulted)) or not present or not dacl:
                raise VaultError("Не удалось создать защищённую ACL")
            result = self._api.SetNamedSecurityInfoW(
                str(path), _SE_FILE_OBJECT,
                _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
                None, None, dacl, None)
            if result != 0:
                raise VaultError("Windows отказал в установке защищённой ACL")
        finally:
            self._kernel.LocalFree(sec_desc)
        self.verify(path)

    def verify(self, path: Path) -> None:
        """Проверяет: DACL защищена, один ACE текущего SID с полным доступом."""
        self.reject_reparse(path, required=True)
        sec_desc = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        rc = self._api.GetNamedSecurityInfoW(
            str(path), _SE_FILE_OBJECT, _DACL_SECURITY_INFORMATION,
            None, None, ctypes.byref(dacl), None, ctypes.byref(sec_desc))
        if rc != 0 or not sec_desc:
            raise VaultError("Не удалось прочитать ACL защищённого хранилища")
        try:
            control, rev = wintypes.WORD(0), wintypes.DWORD(0)
            if not self._api.GetSecurityDescriptorControl(
                    sec_desc, ctypes.byref(control), ctypes.byref(rev)):
                raise VaultError("Не удалось подтвердить DACL")
            if not control.value & _SE_DACL_PROTECTED or not dacl:
                raise VaultError("Обнаружена наследуемая или отсутствующая ACL")
            info = _AclSizeInformation()
            if not self._api.GetAclInformation(
                    dacl, ctypes.byref(info), ctypes.sizeof(info), _ACL_SIZE_INFORMATION):
                raise VaultError("Не удалось проверить разрешения Windows")
            if info.AceCount != 1:
                raise VaultError("Хранилище имеет посторонние права доступа")
            ace = ctypes.c_void_p()
            if not self._api.GetAce(dacl, 0, ctypes.byref(ace)) or not ace:
                raise VaultError("Не удалось проверить разрешение пользователя")
            hdr = ctypes.cast(ace, ctypes.POINTER(_AceHeader)).contents
            if (hdr.AceType != _ACCESS_ALLOWED_ACE_TYPE or hdr.AceFlags != 0
                    or hdr.Mask != _FILE_ALL_ACCESS or hdr.AceSize < 20):
                raise VaultError("Недостаточно ограничений в ACL")
            ref_sid = ctypes.c_void_p()
            if not self._api.ConvertStringSidToSidW(self._sid, ctypes.byref(ref_sid)):
                raise VaultError("Невозможно сопоставить Windows SID")
            try:
                # ACCESS_ALLOWED_ACE: ACE_HEADER[4] + ACCESS_MASK[4] + SID[...]
                stored_sid = ctypes.c_void_p(ace.value + 8)
                if not self._api.EqualSid(ref_sid, stored_sid):
                    raise VaultError("Права принадлежат другому Windows SID")
            finally:
                self._kernel.LocalFree(ref_sid)
        finally:
            self._kernel.LocalFree(sec_desc)
