"""Read-only Windows process discovery. No process modification or token access.

A running process does not prove that it refreshed its authorization state.
"""
from __future__ import annotations

import csv
import io
import locale
import os
import subprocess
from dataclasses import dataclass

_NAMES = {
    "antigravity.exe",
    "language_server.exe",
    "agy.exe",
    "antigravity ide.exe",
}


@dataclass(frozen=True)
class ProcessIdentity:
    image_name: str
    pid: int


def parse_tasklist(output: str) -> tuple[ProcessIdentity, ...]:
    """Parse tasklist /fo csv /nh without relying on localized headers."""
    processes = []
    for row in csv.reader(io.StringIO(output)):
        if len(row) < 2:
            continue
        name = row[0].strip().casefold()
        if name not in _NAMES:
            continue
        try:
            pid = int(row[1].strip())
        except ValueError:
            continue
        if 0 < pid <= 4294967295:
            processes.append(ProcessIdentity(name, pid))
    return tuple(sorted(set(processes), key=lambda p: (p.image_name, p.pid)))


def running_components() -> tuple[ProcessIdentity, ...]:
    """Inspect known Antigravity process names only, without changing them."""
    if os.name != "nt":
        raise OSError("Windows-only process diagnostics")
    result = subprocess.run(
        ["tasklist.exe", "/fo", "csv", "/nh"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=8,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    output = result.stdout.decode(locale.getpreferredencoding(False), "replace")
    return parse_tasklist(output)


def windows_process_start_marker(pid: int) -> str | None:
    """Return Windows process creation FILETIME without reading process memory.

    The marker helps distinguish process restart from PID reuse. Insufficient
    permissions, exited processes, or non-Windows systems yield no marker.
    """
    if os.name != "nt" or not isinstance(pid, int) or pid <= 0:
        return None
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    api.OpenProcess.restype = wintypes.HANDLE
    api.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    )
    api.GetProcessTimes.restype = wintypes.BOOL
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    handle = api.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        started = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not api.GetProcessTimes(
            handle,
            ctypes.byref(started),
            ctypes.byref(exited),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        value = (started.dwHighDateTime << 32) | started.dwLowDateTime
        return f"{value:016x}" if value else None
    finally:
        api.CloseHandle(handle)
