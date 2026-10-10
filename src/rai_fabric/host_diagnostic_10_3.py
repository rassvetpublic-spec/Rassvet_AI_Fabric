"""RAiF 10.3 bounded read-only Windows checkout diagnosis.

Inspect ONE existing local checkout; never fetch, checkout, reset, repair,
run hooks, read credentials, or run any code from that checkout. Every
public outcome uses fixed codes; no filesystem paths or stderr are emitted.
A positive result is only a Git source preflight, not Fabric host QA.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

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


@dataclass(frozen=True)
class Probe:
    status: str
    value: str = ""


def _report(code: str, *, stage: str = "PREFLIGHT", git_reads: int = 0,
            source_class: str = "UNKNOWN") -> dict:
    return {"protocol": "RAIF_FABRIC_HOST_DIAGNOSTIC_10_3/1",
            "verdict": code, "stage": stage, "git_reads": git_reads,
            "source_class": source_class, "target_pin": MAIN_SHA,
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


def _invoke_git(source: Path, git_exe: str, args: tuple[str, ...]) -> Probe:
    """Read local metadata only. Does not log or return stderr/credentials."""
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
    try:
        proc = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              shell=False, timeout=8, check=False)
    except subprocess.TimeoutExpired:
        return Probe("GIT_TIMEOUT")
    except OSError:
        return Probe("GIT_EXEC_FAILURE")
    if len(proc.stdout) > _MAX_BYTES or len(proc.stderr) > _MAX_BYTES:
        return Probe("GIT_OUTPUT_BOUNDED_ABORT")
    if proc.returncode:
        return Probe(_classify_git_stderr(proc.stderr))
    try:
        return Probe("OK", proc.stdout.decode("utf-8", "strict").strip())
    except UnicodeDecodeError:
        return Probe("GIT_OUTPUT_ENCODING_BLOCKED")


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


def _pin_class(sha: str) -> str:
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
    git_exe = shutil.which("git.exe" if sys.platform == "win32" else "git")
    if not git_exe:
        return _report("GIT_EXECUTABLE_MISSING", stage="GIT")
    executable = Path(git_exe)
    if (not executable.is_absolute() or not executable.is_file()
            or source == executable or source in executable.parents
            or "windowsapps" in {part.casefold() for part in executable.parts}):
        return _report("GIT_EXECUTABLE_UNTRUSTED", stage="GIT")
    if _unsafe_ancestor(executable):
        return _report("GIT_EXECUTABLE_UNSAFE", stage="GIT")
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
            return _report("HOST_IGNORED_FILES_PRESENT", stage=stage,
                           git_reads=reads, source_class=klass)
        elif stage == "HEAD_RECHECK" and _pin_class(result.value) != klass:
            return _report("HOST_HEAD_MOVED_DURING_PROBE", stage=stage,
                           git_reads=reads, source_class=klass)
    verdict = ("HOST_MAIN_10_3_CLEAN_PREFLIGHT_ONLY" if klass == "MAIN_10_3_EXACT"
               else "HOST_KNOWN_LEGACY_PIN_CLEAN_NO_UPDATE")
    return _report(verdict, stage="COMPLETE", git_reads=reads, source_class=klass)


def main() -> int:
    report = inspect_clone(Path(r"C:\GIT\Rassvet_AI_Fabric"))
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["verdict"] in ("HOST_MAIN_10_3_CLEAN_PREFLIGHT_ONLY",
                                      "HOST_KNOWN_LEGACY_PIN_CLEAN_NO_UPDATE") else 2


if __name__ == "__main__":
    raise SystemExit(main())
