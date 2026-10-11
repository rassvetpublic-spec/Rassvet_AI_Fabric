"""Read-only Windows host preflight for Fabric 10.1B pinned-source acceptance.

Does not clone, checkout, fetch, run models, create worktrees, or mutate Git.
Never treats a missing or differently checked-out clone as permission to
change it. Only returns bounded fixed status codes, not local user paths.
"""
from __future__ import annotations

__version__ = "1.0.0"

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

PIN = "a0daf08375b70d202b3dc7b5ab51f894e87d9ae0"
_ALLOWED_ORIGINS = frozenset((
    "https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric.git",
    "https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric",
    "git@github.com:rassvetpublic-spec/Rassvet_AI_Fabric.git",
))
_MAX_OUTPUT = 64 * 1024


def _result(verdict: str) -> dict:
    return {"verdict": verdict, "pin": PIN,
            "read_only": True, "network_calls": 0,
            "source_mutations": 0, "model_turns": 0,
            "targeted_20_tests_executed": False,
            "full_10_1b_acceptance_verified": False}


def _git(source: Path, *args: str) -> str | None:
    env = os.environ.copy()
    for key in tuple(env):
        if key.upper().startswith("GIT_") or key == "GCM_INTERACTIVE":
            env.pop(key, None)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1",
                "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull, "GCM_INTERACTIVE": "never",
                "GIT_LFS_SKIP_SMUDGE": "1"})
    prefix = ("git", "--no-optional-locks", "-c", "credential.helper=",
              "-c", "core.fsmonitor=false", "-c", "protocol.ext.allow=never",
              "-C", str(source))
    try:
        completed = subprocess.run((*prefix, *args), env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   shell=False, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or len(completed.stdout) > _MAX_OUTPUT:
        return None
    try:
        return completed.stdout.decode("utf-8", "strict").strip()
    except UnicodeDecodeError:
        return None


def _unsafe_path(path: Path) -> bool:
    current = path
    while True:
        try:
            if current.is_symlink() or (current.exists() and
                    getattr(current.lstat(), "st_file_attributes", 0) & 0x400):
                return True
        except OSError:
            return True
        if current.parent == current:
            return False
        current = current.parent


def inspect_fabric_clone(path: Path, *, windows_override_for_tests: bool = False) -> dict:
    """Inspect one existing checkout only; never download or change its ref."""
    if sys.platform != "win32" and not windows_override_for_tests:
        return _result("WINDOWS_ONLY")
    if not isinstance(path, Path) or _unsafe_path(path):
        return _result("HOST_PATH_UNSAFE")
    if not path.is_dir() or not (path / ".git").is_dir():
        return _result("HOST_CLONE_NOT_PRESENT_OR_NONSTANDARD")
    root = _git(path, "rev-parse", "--show-toplevel")
    if root is None:
        return _result("HOST_CLONE_READ_FAILED")
    try:
        if Path(root).resolve() != path.resolve():
            return _result("HOST_CLONE_ROOT_MISMATCH")
    except (OSError, ValueError):
        return _result("HOST_CLONE_ROOT_MISMATCH")
    origin = _git(path, "remote", "get-url", "origin")
    if origin not in _ALLOWED_ORIGINS:
        return _result("HOST_ORIGIN_NOT_PINNED")
    head = _git(path, "rev-parse", "HEAD")
    if head != PIN:
        return _result("HOST_HEAD_NOT_PINNED_NO_MUTATION")
    dirty = _git(path, "status", "--porcelain=v1", "--untracked-files=all")
    if dirty is None or dirty:
        return _result("HOST_CLONE_UNCLEAN_OR_STATUS_FAILED")
    ignored = _git(path, "ls-files", "--others", "--ignored", "--exclude-standard")
    if ignored is None or ignored:
        return _result("HOST_CLONE_IGNORED_FILES_UNKNOWN")
    return _result("HOST_PIN_READONLY_PREFLIGHT_PASS")
