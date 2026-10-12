"""RAiF 10.3 bounded read-only Windows checkout diagnosis.

Inspect ONE existing local checkout; never fetch, checkout, reset, repair,
run hooks, read credentials, or run any code from that checkout. Every
public outcome uses fixed codes; no filesystem paths or stderr are emitted.
A positive result is only a Git source preflight, not Fabric host QA.
"""
from __future__ import annotations

__version__ = "1.0.0"

import json
import hashlib
import hmac
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import sys
from dataclasses import dataclass
from pathlib import Path

MAIN_10_4_SHA = "34e5f83652b65a4924fb48ff5aeeb90dde2783a7"
MAIN_SHA = "8dc6ee32eabd3334012763bac8e641f682e478c6"
LEGACY_10_1_SHA = "a0daf08375b70d202b3dc7b5ab51f894e87d9ae0"
AG_BASE_SHA = "4032b73bcdbc2e355898953439194e7a077d90e0"
_ORIGINS = frozenset({
    "https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric.git",
    "https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric",
    "git@github.com:rassvetpublic-spec/Rassvet_AI_Fabric.git",
})
_MAX_BYTES = 32 * 1024
_REPARSE = 0x400
# Operator-confirmed Git for Windows location. Still validate the executable before use.
_WINDOWS_GIT_CMD = Path(r"C:\Program Files\Git\cmd\git.exe")
# SHA-256 independently reported by owner's W0 fixed-path readback.
# A changed installation requires an explicit new trust decision.
_WINDOWS_GIT_SHA256 = "78211c7ed73988da93a6d8a33d47ec6187f464d7ea2a9a00c182bbd7a1ecf30f"
_TRUSTED_WINDOWS_GIT_SHA256 = frozenset({
    "78211c7ed73988da93a6d8a33d47ec6187f464d7ea2a9a00c182bbd7a1ecf30f",
    "54bda91c773c6bba2b970424423cfcb80552d92dc6967d766f98931fe1251a54",
})
_READ_CHUNK = 4096


@dataclass(frozen=True)
class Probe:
    status: str
    value: str = ""


def _report(code: str, *, stage: str = "PREFLIGHT", git_reads: int = 0,
            source_class: str = "UNKNOWN") -> dict:
    pin = MAIN_10_4_SHA if source_class == "MAIN_10_4_EXACT" else MAIN_SHA
    return {"protocol": "RAIF_FABRIC_HOST_DIAGNOSTIC_10_3/1",
            "verdict": code, "stage": stage, "git_reads": git_reads,
            "source_class": source_class, "target_pin": pin,
            "network_calls": 0, "source_mutations": 0, "model_calls": 0,
            "credentials_read": False, "host_qa_verified": False,
            "merge_authorized": False, "run_local_code": False}


def _classify_git_stderr(body: bytes) -> str:
    """Recognize bounded Git problems without exposing untrusted stderr."""
    lower = body[:_MAX_BYTES].lower()
    if b"dubious ownership" in lower or b"safe.directory" in lower:
        return "GIT_SAFE_DIRECTORY_REJECTED"
    if b"not a git repository" in lower:
        return "GIT_NOT_REPOSITORY"
    if b"permission denied" in lower or b"access is denied" in lower:
        return "GIT_ACCESS_DENIED"
    if b"detected unsafe repository" in lower:
        return "GIT_UNSAFE_REPOSITORY"
    return "GIT_COMMAND_REJECTED"


def _capture_bounded(argv: list[str], env: dict[str, str], *,
                     timeout_seconds: float = 8.0) -> Probe:
    """Capture two child streams with bounded resident buffers on Windows.

    Both pipes are drained concurrently; a limit violation terminates the
    owned child. No stdout/stderr text is logged or forwarded to the caller.
    """
    try:
        child = subprocess.Popen(
            argv, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
        )
    except OSError:
        return Probe("GIT_EXEC_FAILURE")
    assert child.stdout is not None and child.stderr is not None
    parts = [bytearray(), bytearray()]
    overflow = threading.Event()
    reader_error = threading.Event()

    def drain(stream, target: bytearray) -> None:
        try:
            while not overflow.is_set():
                # Read at most one byte beyond the limit, never all child output.
                remaining = _MAX_BYTES + 1 - len(target)
                chunk = os.read(stream.fileno(), min(_READ_CHUNK, remaining))
                if not chunk:
                    return
                space = _MAX_BYTES - len(target)
                if len(chunk) > space:
                    target.extend(chunk[:space])
                    overflow.set()
                    return
                target.extend(chunk)
        except (OSError, ValueError):
            reader_error.set()

    readers = [
        threading.Thread(target=drain, args=(child.stdout, parts[0]), daemon=True),
        threading.Thread(target=drain, args=(child.stderr, parts[1]), daemon=True),
    ]
    for thread in readers:
        thread.start()
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            if overflow.is_set():
                return Probe("GIT_OUTPUT_BOUNDED_ABORT")
            if reader_error.is_set():
                return Probe("GIT_EXEC_FAILURE")
            if child.poll() is not None and not any(x.is_alive() for x in readers):
                break
            if time.monotonic() >= deadline:
                return Probe("GIT_TIMEOUT")
            time.sleep(0.015)
        if child.returncode:
            return Probe(_classify_git_stderr(bytes(parts[1])))
        try:
            return Probe("OK", bytes(parts[0]).decode("utf-8", "strict").strip())
        except UnicodeDecodeError:
            return Probe("GIT_OUTPUT_ENCODING_BLOCKED")
    finally:
        # Only the child created above is killed/reaped; never a foreign PID.
        try:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            try:
                child.kill()
                child.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
        for pipe in (child.stdout, child.stderr):
            try:
                pipe.close()
            except OSError:
                pass
        for thread in readers:
            thread.join(timeout=1)


def _invoke_git(source: Path, git_exe: str, args: tuple[str, ...]) -> Probe:
    """Read local Git metadata without accumulating untrusted pipe output."""
    env = os.environ.copy()
    for key in tuple(env):
        if key.upper().startswith("GIT_") or key == "GCM_INTERACTIVE":
            env.pop(key, None)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1",
                "GIT_LFS_SKIP_SMUDGE": "1"})
    argv = [git_exe, "--no-optional-locks", "-c", "credential.helper=",
            "-c", "core.fsmonitor=false", "-c", "core.hooksPath=NUL",
            "-c", "submodule.recurse=false", "-c", "protocol.ext.allow=never",
            "-C", str(source), *args]
    return _capture_bounded(argv, env)


def _unsafe_ancestor(path: Path) -> bool:
    """Block symlinks, Windows junctions and unreadable ancestors."""
    current = path
    while True:
        try:
            meta = current.lstat()
            if stat.S_ISLNK(meta.st_mode) or getattr(meta, "st_file_attributes", 0) & _REPARSE:
                return True
        except FileNotFoundError:
            pass
        except OSError:
            return True
        if current.parent == current:
            return False
        current = current.parent


def _resolve_git_executable(*, windows_override_for_tests: bool = False) -> str | None:
    """Prefer the operator-confirmed installation before PATH (no PATH mutation).

    PATH fallback permits other legitimate installations. The caller retains
    the absolute-path, source-containment and reparse checks before execution.
    """
    is_windows = sys.platform == "win32" or windows_override_for_tests
    if is_windows:
        # An arbitrary PATH candidate has no owner-attested publisher/hash.
        # Fail closed if the only approved Windows executable is unavailable.
        return str(_WINDOWS_GIT_CMD) if _WINDOWS_GIT_CMD.is_file() else None
    return shutil.which("git")


def _pin_class(sha: str) -> str:
    if sha == MAIN_10_4_SHA:
        return "MAIN_10_4_EXACT"
    if sha == MAIN_SHA:
        return "MAIN_10_3_EXACT"
    if sha == LEGACY_10_1_SHA:
        return "LEGACY_10_1_EXACT"
    if sha == AG_BASE_SHA:
        return "AG_PATHER_PREVIOUS_EXACT"
    return "UNRECOGNIZED_HEAD"


def inspect_clone(source: Path, *, windows_override_for_tests: bool = False) -> dict:
    """Classify failure stage and Git metadata without changing the checkout."""
    if sys.platform != "win32" and not windows_override_for_tests:
        return _report("WINDOWS_ONLY")
    if not isinstance(source, Path) or not source.is_absolute() or ".." in source.parts:
        return _report("HOST_PATH_INVALID")
    if _unsafe_ancestor(source):
        return _report("HOST_REPARSE_OR_PERMISSION_BLOCKED", stage="PATH")
    if not source.is_dir():
        return _report("HOST_DIRECTORY_MISSING", stage="PATH")
    gitdir = source / ".git"
    if _unsafe_ancestor(gitdir):
        return _report("HOST_GIT_DIR_REPARSE_BLOCKED", stage="PATH")
    if gitdir.is_file():
        return _report("HOST_WORKTREE_GITFILE_UNSUPPORTED", stage="PATH")
    if not gitdir.is_dir():
        return _report("HOST_GIT_DIRECTORY_MISSING", stage="PATH")
    if _unsafe_ancestor(gitdir / "config"):
        return _report("HOST_GIT_CONFIG_REPARSE_BLOCKED", stage="PATH")
    if not (gitdir / "config").is_file():
        return _report("HOST_GIT_CONFIG_MISSING", stage="PATH")
    git_exe = _resolve_git_executable(windows_override_for_tests=windows_override_for_tests)
    if not git_exe:
        return _report("GIT_EXECUTABLE_MISSING", stage="GIT")
    executable = Path(git_exe)
    if (not executable.is_absolute() or not executable.is_file()
            or source == executable or source in executable.parents
            or "windowsapps" in {part.casefold() for part in executable.parts}):
        return _report("GIT_EXECUTABLE_UNTRUSTED", stage="GIT")
    if _unsafe_ancestor(executable):
        return _report("GIT_EXECUTABLE_UNSAFE", stage="GIT")
    if sys.platform == "win32" or windows_override_for_tests:
        # The path is explicitly owner-confirmed, but its bytes may change.
        try:
            if executable.stat().st_size > 64 * 1024 * 1024:
                return _report("GIT_EXECUTABLE_UNTRUSTED", stage="GIT")
            with executable.open("rb") as stream:
                actual_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError:
            return _report("GIT_EXECUTABLE_UNTRUSTED", stage="GIT")
        if not (hmac.compare_digest(actual_sha256, _WINDOWS_GIT_SHA256)
                or actual_sha256 in _TRUSTED_WINDOWS_GIT_SHA256):
            return _report("GIT_EXECUTABLE_HASH_MISMATCH", stage="GIT")
    steps = (("ROOT", ("rev-parse", "--show-toplevel")),
             ("ORIGIN", ("remote", "get-url", "origin")),
             ("HEAD", ("rev-parse", "HEAD")),
             ("STATUS", ("status", "--porcelain=v1", "--untracked-files=all")),
             ("IGNORED", ("ls-files", "--others", "--ignored", "--exclude-standard")),
             ("HEAD_RECHECK", ("rev-parse", "HEAD")))
    reads = 0
    klass = "UNKNOWN"
    for stage, argv in steps:
        result = _invoke_git(source, git_exe, argv)
        reads += 1
        if result.status != "OK":
            return _report("HOST_" + stage + "_" + result.status,
                           stage=stage, git_reads=reads, source_class=klass)
        if stage == "ROOT":
            try:
                if Path(result.value).resolve(strict=True) != source.resolve(strict=True):
                    return _report("HOST_ROOT_MISMATCH", stage=stage, git_reads=reads)
            except (OSError, ValueError):
                return _report("HOST_ROOT_UNVERIFIABLE", stage=stage, git_reads=reads)
        elif stage == "ORIGIN" and result.value not in _ORIGINS:
            return _report("HOST_ORIGIN_UNEXPECTED", stage=stage, git_reads=reads)
        elif stage == "HEAD":
            if not re.fullmatch(r"[0-9a-f]{40}", result.value):
                return _report("HOST_HEAD_INVALID", stage=stage, git_reads=reads)
            klass = _pin_class(result.value)
            if klass == "UNRECOGNIZED_HEAD":
                return _report("HOST_HEAD_NOT_KNOWN", stage=stage, git_reads=reads,
                               source_class=klass)
        elif stage == "STATUS" and result.value:
            return _report("HOST_WORKTREE_NOT_CLEAN", stage=stage, git_reads=reads,
                           source_class=klass)
        elif stage == "IGNORED" and result.value:
            lines = [line.strip().replace("\\", "/") for line in result.value.splitlines() if line.strip()]
            non_ephemeral = [
                line for line in lines
                if not (line.endswith(".pyc") or line.endswith(".pyo")
                        or "/__pycache__/" in line or line.startswith("__pycache__/")
                        or line.startswith("docs/BPR5") or line.startswith("docs/BPR5_REVIEW")
                        or line.startswith("outputs/"))
            ]
            if non_ephemeral:
                return _report("HOST_IGNORED_FILES_PRESENT", stage=stage,
                               git_reads=reads, source_class=klass)
        elif stage == "HEAD_RECHECK" and _pin_class(result.value) != klass:
            return _report("HOST_HEAD_MOVED_DURING_PROBE", stage=stage,
                           git_reads=reads, source_class=klass)
    verdict = ("HOST_MAIN_10_4_CLEAN_PREFLIGHT_ONLY" if klass == "MAIN_10_4_EXACT"
               else "HOST_MAIN_10_3_CLEAN_PREFLIGHT_ONLY" if klass == "MAIN_10_3_EXACT"
               else "HOST_KNOWN_LEGACY_PIN_CLEAN_NO_UPDATE")
    return _report(verdict, stage="COMPLETE", git_reads=reads, source_class=klass)


def main() -> int:
    source_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\GIT\Rassvet_AI_Fabric")
    report = inspect_clone(source_arg)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["verdict"] in ("HOST_MAIN_10_4_CLEAN_PREFLIGHT_ONLY",
                                      "HOST_MAIN_10_3_CLEAN_PREFLIGHT_ONLY",
                                      "HOST_KNOWN_LEGACY_PIN_CLEAN_NO_UPDATE") else 2


if __name__ == "__main__":
    raise SystemExit(main())
