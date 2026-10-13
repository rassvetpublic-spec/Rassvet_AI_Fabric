# -*- coding: utf-8 -*-
"""
src.raif_ag_supervisor.session_adapter - Нативный адаптер сессий и горячей смены аккаунтов Antigravity.
Реализует паттерн Child Respawn (Pre-write -> Terminate child LS -> Post-write -> Await Respawn)
в соответствии со спецификацией RFC_ACCOUNT_SWITCH_MECHANICS и Master Plan CP-54.

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / MTD 011011.
"""
from __future__ import annotations

__version__ = "1.0.0"

import os
import sys
import time
import json
import ctypes
from ctypes import wintypes
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

from .session_probe import running_components, windows_process_start_marker, ProcessIdentity


# Константы Win32 Credential Manager
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_NOT_FOUND = 1168

# Константы Win32 процессов
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Целевая нативная запись Antigravity
DEFAULT_TARGET_NAME = "gemini:antigravity"
DEFAULT_USER_NAME = "antigravity"


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


class SessionAdapterError(RuntimeError):
    """Безопасное исключение без раскрытия токенов или персональных данных."""


@dataclass(frozen=True)
class SwitchResult:
    status: str
    target: str
    old_pid: Optional[int]
    new_pid: Optional[int]
    duration_ms: float
    rolled_back: bool
    details: str

    def safe_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "target": self.target,
            "old_pid": self.old_pid,
            "new_pid": self.new_pid,
            "duration_ms": round(self.duration_ms, 2),
            "rolled_back": self.rolled_back,
            "details": self.details,
        }


class StandaloneSessionAdapter:
    """Управление нативной сессией Antigravity Standalone через Credential Manager и Child Respawn."""

    def __init__(self, target_name: str = DEFAULT_TARGET_NAME) -> None:
        self.target_name = target_name
        self._is_windows = (os.name == "nt")
        if self._is_windows:
            self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._setup_winapi()

    def _setup_winapi(self) -> None:
        # advapi32
        self._advapi32.CredWriteW.argtypes = (_PCREDENTIALW, wintypes.DWORD)
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredReadW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(_PCREDENTIALW),
        )
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        )
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = (ctypes.c_void_p,)
        self._advapi32.CredFree.restype = None

        # kernel32
        self._kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        self._kernel32.TerminateProcess.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    def read_native_credential_bytes(self) -> Optional[bytes]:
        """Чтение сырых байтов целевой записи Credential Manager."""
        if not self._is_windows:
            return None
        pointer = _PCREDENTIALW()
        if not self._advapi32.CredReadW(self.target_name, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            code = ctypes.get_last_error()
            if code == _NOT_FOUND:
                return None
            raise SessionAdapterError(f"CredReadW failed ({code})")
        try:
            raw = ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize)
            return bytes(raw)
        finally:
            self._advapi32.CredFree(ctypes.cast(pointer, ctypes.c_void_p))

    def read_native_credential_json(self) -> Optional[Dict[str, Any]]:
        """Чтение и валидация структуры JSON целевой записи."""
        raw = self.read_native_credential_bytes()
        if not raw:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise SessionAdapterError("native credential is not a JSON object")
            return data
        except UnicodeError as exc:
            raise SessionAdapterError("native credential is not valid UTF-8") from exc
        except json.JSONDecodeError as exc:
            raise SessionAdapterError("native credential JSON syntax error") from exc

    def write_native_credential_bytes(self, raw_bytes: bytes, user_name: str = DEFAULT_USER_NAME) -> bool:
        """Атомарная запись сырых байтов в target Credential Manager."""
        if not self._is_windows:
            return False
        if not isinstance(raw_bytes, (bytes, bytearray)) or not raw_bytes:
            raise SessionAdapterError("invalid credential payload")

        buffer = ctypes.create_string_buffer(bytes(raw_bytes), len(raw_bytes))
        try:
            entry = _CREDENTIALW()
            entry.Type = _CRED_TYPE_GENERIC
            entry.TargetName = self.target_name
            entry.UserName = user_name
            entry.CredentialBlobSize = len(raw_bytes)
            entry.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            entry.Persist = _CRED_PERSIST_LOCAL_MACHINE
            success = bool(self._advapi32.CredWriteW(ctypes.byref(entry), 0))
            if not success:
                code = ctypes.get_last_error()
                raise SessionAdapterError(f"CredWriteW failed ({code})")
            return True
        finally:
            ctypes.memset(buffer, 0, len(raw_bytes))

    def write_native_credential_json(self, data: Dict[str, Any], user_name: str = DEFAULT_USER_NAME) -> bool:
        """Сериализация словаря в JSON и запись в Credential Manager."""
        if not isinstance(data, dict):
            raise SessionAdapterError("credential data must be a dictionary")
        payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return self.write_native_credential_bytes(payload, user_name=user_name)

    def find_language_server_process(self) -> Optional[ProcessIdentity]:
        """Поиск активного процесса language_server.exe."""
        if not self._is_windows:
            return None
        comps = running_components()
        for c in comps:
            if c.image_name.casefold() == "language_server.exe":
                return c
        return None

    def terminate_language_server(self, pid: int) -> bool:
        """Безопасное завершение только дочернего процесса language_server.exe."""
        if not self._is_windows or pid <= 0:
            return False
        handle = self._kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)
        if not handle:
            code = ctypes.get_last_error()
            raise SessionAdapterError(f"OpenProcess for PID {pid} failed ({code})")
        try:
            return bool(self._kernel32.TerminateProcess(handle, 0))
        finally:
            self._kernel32.CloseHandle(handle)

    def wait_for_respawn(
        self,
        old_pid: int,
        timeout_seconds: float = 6.0,
        poll_interval_seconds: float = 0.2,
    ) -> Optional[int]:
        """Ожидание появления нового language_server.exe с другим PID."""
        deadline = time.perf_counter() + timeout_seconds
        while time.perf_counter() < deadline:
            time.sleep(poll_interval_seconds)
            current = self.find_language_server_process()
            if current and current.pid != old_pid:
                return current.pid
        return None

    def execute_hot_switch(
        self,
        new_credential: Dict[str, Any],
        timeout_seconds: float = 6.0,
    ) -> SwitchResult:
        """Полный цикл горячей смены аккаунта по паттерну Child Respawn с гарантированным откатом."""
        t0 = time.perf_counter()

        if not self._is_windows:
            return SwitchResult(
                status="UNSUPPORTED_OS",
                target=self.target_name,
                old_pid=None,
                new_pid=None,
                duration_ms=0.0,
                rolled_back=False,
                details="Child Respawn hot-switch is supported only on Windows",
            )

        # 1. Снимаем обязательный in-memory snapshot для отката
        original_snapshot = self.read_native_credential_bytes()
        if not original_snapshot:
            return SwitchResult(
                status="PRECHECK_FAILED",
                target=self.target_name,
                old_pid=None,
                new_pid=None,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                rolled_back=False,
                details="Active native credential not found or empty; aborting before changes",
            )

        # 2. Ищем активный language_server.exe
        active_ls = self.find_language_server_process()
        if not active_ls:
            return SwitchResult(
                status="PRECHECK_FAILED",
                target=self.target_name,
                old_pid=None,
                new_pid=None,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                rolled_back=False,
                details="Active language_server.exe process not found",
            )

        old_pid = active_ls.pid
        rolled_back = False

        try:
            # Шаг 1: Pre-write WinCred
            self.write_native_credential_json(new_credential)

            # Шаг 2: Terminate Child LS
            self.terminate_language_server(old_pid)

            # Шаг 3: Post-write assertion (защита от сброса кэша умирающим LS)
            time.sleep(0.1)
            self.write_native_credential_json(new_credential)

            # Шаг 4: Ожидание респауна
            new_pid = self.wait_for_respawn(old_pid, timeout_seconds=timeout_seconds)

            if not new_pid:
                # Тайм-аут респауна -> аварийный откат
                self.write_native_credential_bytes(original_snapshot)
                rolled_back = True
                duration_ms = (time.perf_counter() - t0) * 1000.0
                return SwitchResult(
                    status="TIMEOUT_RESPAWN",
                    target=self.target_name,
                    old_pid=old_pid,
                    new_pid=None,
                    duration_ms=duration_ms,
                    rolled_back=rolled_back,
                    details=f"Language server did not respawn within {timeout_seconds}s; rollback restored",
                )

            duration_ms = (time.perf_counter() - t0) * 1000.0
            return SwitchResult(
                status="SUCCESS",
                target=self.target_name,
                old_pid=old_pid,
                new_pid=new_pid,
                duration_ms=duration_ms,
                rolled_back=False,
                details=f"Child language_server respawned (PID {old_pid} -> {new_pid}) in {duration_ms:.1f}ms",
            )

        except Exception as exc:
            # При любой ошибке немедленно возвращаем исходный снапшот
            try:
                self.write_native_credential_bytes(original_snapshot)
                rolled_back = True
            except Exception:
                pass
            duration_ms = (time.perf_counter() - t0) * 1000.0
            return SwitchResult(
                status="ERROR",
                target=self.target_name,
                old_pid=old_pid,
                new_pid=None,
                duration_ms=duration_ms,
                rolled_back=rolled_back,
                details=f"Exception during switch: {exc}; rollback={rolled_back}",
            )
