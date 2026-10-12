"""W2-C: owned Windows Job Object для ИСКЛЮЧИТЕЛЬНО синтетических детей.

Процесс создаётся СРАЗУ приостановленным, назначается созданному нами Job
и только после этого запускается. Никаких чужих PID/IDE/провайдеров.
"""
from __future__ import annotations

__version__ = "0.1.0"

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from .store import FabricError

_JOB_KILL_ON_CLOSE = 0x00002000
_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_JOB_EXTENDED_INFO = 9
_JOB_BASIC_ACCOUNTING = 1

# Synthetic fixture IDs only: no arbitrary program or prompt execution.
_CASES = {
    "EXIT_ZERO": "raise SystemExit(0)",
    "EXIT_NONZERO": "raise SystemExit(7)",
    "HANG_PARENT": "import time;time.sleep(15)",
    "SPAWN_DESCENDANT": (
        "import subprocess,sys;"
        "subprocess.Popen([sys.executable,'-I','-B','-c',"
        "'import time;time.sleep(15)'],close_fds=True);"
        "raise SystemExit(0)"
    ),
}


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


class _BASIC_LIMITS(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _EXTENDED_LIMITS(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BASIC_LIMITS),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ACCOUNTING(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


def _kernel():
    """Настраивать WinAPI строго на Windows; никакого shell/taskkill."""
    if sys.platform != "win32":
        raise FabricError("WINDOWS_ONLY_JOB_OBJECT")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    api.CreateJobObjectW.restype = handle
    api.SetInformationJobObject.argtypes = [handle, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    api.SetInformationJobObject.restype = wintypes.BOOL
    api.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOW), ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    api.CreateProcessW.restype = wintypes.BOOL
    api.AssignProcessToJobObject.argtypes = [handle, handle]
    api.AssignProcessToJobObject.restype = wintypes.BOOL
    api.ResumeThread.argtypes = [handle]
    api.ResumeThread.restype = wintypes.DWORD
    api.TerminateProcess.argtypes = [handle, wintypes.UINT]
    api.TerminateProcess.restype = wintypes.BOOL
    api.TerminateJobObject.argtypes = [handle, wintypes.UINT]
    api.TerminateJobObject.restype = wintypes.BOOL
    api.WaitForSingleObject.argtypes = [handle, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.GetExitCodeProcess.argtypes = [handle, ctypes.POINTER(wintypes.DWORD)]
    api.GetExitCodeProcess.restype = wintypes.BOOL
    api.QueryInformationJobObject.argtypes = [
        handle, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.QueryInformationJobObject.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [handle]
    api.CloseHandle.restype = wintypes.BOOL
    return api


def _active_count(api, job) -> int:
    info = _ACCOUNTING()
    if not api.QueryInformationJobObject(
        job, _JOB_BASIC_ACCOUNTING, ctypes.byref(info),
        ctypes.sizeof(info), None
    ):
        raise FabricError("WINDOWS_JOB_ACCOUNTING_FAILED")
    return info.ActiveProcesses


def run_synthetic_job(case: str, *, timeout_seconds: float = 3.0,
                      cwd: str | Path | None = None) -> dict:
    """Доказательство владения тестовым дочерним деревом без внешнего inference.

    На отказе до Assign/Resume ребёнок остаётся suspended и принудительно
    уничтожается по его HANDLE, не по произвольному PID.
    """
    if sys.platform != "win32":
        raise FabricError("WINDOWS_ONLY_JOB_OBJECT")
    if case not in _CASES:
        raise FabricError("SYNTHETIC_CASE_NOT_ALLOWED")
    if type(timeout_seconds) not in (float, int) or not 0.1 <= timeout_seconds <= 30.0:
        raise FabricError("WINDOWS_JOB_TIMEOUT_INVALID")
    if cwd is not None and not Path(cwd).is_dir():
        raise FabricError("WINDOWS_JOB_WORKSPACE_MISSING")
    api = _kernel()
    job = api.CreateJobObjectW(None, None)
    if not job:
        raise FabricError("WINDOWS_JOB_CREATE_FAILED")
    pi = _PROCESS_INFORMATION()
    assigned = False
    resumed = False
    try:
        limits = _EXTENDED_LIMITS()
        limits.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_CLOSE
        if not api.SetInformationJobObject(
            job, _JOB_EXTENDED_INFO, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            raise FabricError("WINDOWS_JOB_LIMITS_FAILED")
        program = str(Path(sys.executable).absolute())
        args = [program, "-I", "-B", "-c", _CASES[case]]
        commandline = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
        si = _STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        ok = api.CreateProcessW(
            program, commandline, None, None, False,
            _CREATE_SUSPENDED | _CREATE_NO_WINDOW,
            None, str(Path(cwd).absolute()) if cwd is not None else None,
            ctypes.byref(si), ctypes.byref(pi),
        )
        if not ok:
            raise FabricError("WINDOWS_CHILD_CREATE_FAILED")
        if not api.AssignProcessToJobObject(job, pi.hProcess):
            raise FabricError("WINDOWS_JOB_ASSIGNMENT_REJECTED")
        assigned = True
        if api.ResumeThread(pi.hThread) == 0xFFFFFFFF:
            raise FabricError("WINDOWS_JOB_RESUME_FAILED")
        resumed = True
        deadline = time.monotonic() + float(timeout_seconds)
        while _active_count(api, job) != 0:
            if time.monotonic() >= deadline:
                if not api.TerminateJobObject(job, 1):
                    raise FabricError("WINDOWS_JOB_TERMINATE_FAILED")
                grace = time.monotonic() + 2.0
                while _active_count(api, job) and time.monotonic() < grace:
                    time.sleep(0.025)
                if _active_count(api, job):
                    raise FabricError("WINDOWS_JOB_OWNED_CHILDREN_UNVERIFIED")
                return {
                    "verdict": "OWNED_GROUP_TERMINATED",
                    "owned_job": True, "descendants_active": 0,
                    "external_provider_calls": 0, "synthetic": True,
                }
            time.sleep(0.025)
        code = wintypes.DWORD()
        if not api.GetExitCodeProcess(pi.hProcess, ctypes.byref(code)):
            raise FabricError("WINDOWS_JOB_EXIT_UNVERIFIED")
        return {
            "verdict": "EXITED",
            "exit_code": int(code.value),
            "owned_job": True, "descendants_active": 0,
            "external_provider_calls": 0, "synthetic": True,
        }
    finally:
        # Always release owned handles; KILL_ON_JOB_CLOSE is the final safety net.
        if pi.hProcess:
            if not assigned or not resumed:
                api.TerminateProcess(pi.hProcess, 1)
                api.WaitForSingleObject(pi.hProcess, 2000)
            if pi.hThread:
                api.CloseHandle(pi.hThread)
            api.CloseHandle(pi.hProcess)
        api.CloseHandle(job)
