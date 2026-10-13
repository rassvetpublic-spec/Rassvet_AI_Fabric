"""RAiF 10.1: Windows-only, offline, fail-closed Git worktree diff review.

This module never invokes Codex, a model API, a network fetch, Git push, merge,
reset, or a user-supplied test executable. A review is not approval to merge.
"""
from __future__ import annotations

__version__ = "1.0.0"

import argparse
import ctypes
import ast
import difflib
import hashlib
import json
import os
import re
import queue
import threading
import time
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PIN = re.compile(r"[0-9a-fA-F]{40}\Z")
COMPONENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")
FORBIDDEN = {".git", ".github", ".gitmodules", ".gitattributes", "_raif_runtime",
             "bpr40", "cks", "ruleshub", "control_tower", "antigravitydata"}
PROTECTED_FILES = {"agents.md", "pyproject.toml", ".gitignore", "readme.md"}
MAX_FILES = 12
MAX_FILE_BYTES = 128 * 1024
MAX_TOTAL_BYTES = 384 * 1024
MAX_PATCH_BYTES = 768 * 1024
MOCK_PATH = "sandbox_demo/arithmetic.py"
MOCK_SOURCE = "def add(a, b):\n    return a + b\n"
NEXT_REVIEW = "RAI-FABRIC/10.1-SAFE_WORKTREE_DIFF_REVIEW_OFFLINE"
NEXT_WINDOWS = "RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE"
SECRET_MARKERS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----", re.I),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:Authorization\s*:\s*Bearer|Cookie\s*:|Set-Cookie\s*:)", re.I),
    re.compile(r"\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password)\s*[=:]\s*['\"]?[^\s'\"]{12,}", re.I),
)


class ReviewBlocked(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


try:
    from rai_fabric.fleet_common import sha256_bytes
except ImportError:
    from fleet_common import sha256_bytes  # type: ignore

sha256 = sha256_bytes


def _windows_only() -> None:
    if sys.platform != "win32" or sys.version_info < (3, 11):
        raise ReviewBlocked("WINDOWS_PYTHON_311_REQUIRED")


def _is_reparse(path: Path) -> bool:
    try:
        meta = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(meta, "st_file_attributes", 0) & 0x400)


def _assert_local_volume(path: Path) -> None:
    """Block UNC and mapped SMB drives; offline means no network filesystem."""
    drive = path.anchor
    if not drive or drive.startswith("\\\\"):
        raise ReviewBlocked("LOCAL_DRIVE_REQUIRED")
    try:
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
    except (AttributeError, OSError) as exc:
        raise ReviewBlocked("LOCAL_DRIVE_UNVERIFIED") from exc
    if drive_type not in (2, 3):  # removable or fixed local volume only
        raise ReviewBlocked("NETWORK_OR_NONLOCAL_VOLUME_BLOCKED")


def _assert_no_reparse(path: Path) -> None:
    current = path
    while True:
        if _is_reparse(current):
            raise ReviewBlocked("REPARSE_POINT_BLOCKED")
        if current.parent == current:
            break
        current = current.parent


def _strict_path(path: str) -> str:
    if (not isinstance(path, str) or len(path) > 180 or "\\" in path or ":" in path
            or path.startswith("/") or path.endswith("/") or "//" in path):
        raise ReviewBlocked("UNSAFE_RELATIVE_PATH")
    parts = path.split("/")
    if not parts or any(part in ("", ".", "..") or not COMPONENT.fullmatch(part)
                        or part.endswith(".") or part.endswith(" ") for part in parts):
        raise ReviewBlocked("UNSAFE_RELATIVE_PATH")
    if any(part.lower() in FORBIDDEN for part in parts) or path.lower() in PROTECTED_FILES:
        raise ReviewBlocked("PROTECTED_PATH")
    # Reject NTFS alternate streams / Win32 device names and trailing-dot ambiguities.
    for part in parts:
        stem = part.split(".", 1)[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", stem):
            raise ReviewBlocked("RESERVED_WINDOWS_NAME")
    return path


def _allowed(values: list[str]) -> list[str]:
    if not 1 <= len(values) <= MAX_FILES:
        raise ReviewBlocked("ALLOWLIST_COUNT_INVALID")
    normalized = [_strict_path(v) for v in values]
    if len({v.casefold() for v in normalized}) != len(normalized):
        raise ReviewBlocked("ALLOWLIST_CASE_COLLISION")
    return sorted(normalized)


def _git(repo: Path, *args: str, timeout: int = 25, hooks: Path | None = None) -> bytes:
    """Git execution with a hard pre-capture output bound and elapsed deadline.

    This hardened candidate is NOT the published pinned-source version until
    a new commit, Windows regression and explicit integration gate.
    """
    env = os.environ.copy()
    for key in list(env):
        if key.upper().startswith("GIT_"):
            env.pop(key)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
                "GIT_LFS_SKIP_SMUDGE": "1", "GIT_NO_LAZY_FETCH": "1",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    flags = ["-c", "core.fsmonitor=false", "-c", "core.sparseCheckout=false",
             "-c", "core.untrackedCache=false"]
    if hooks is not None:
        flags.extend(["-c", f"core.hooksPath={hooks}"])
    limit = MAX_PATCH_BYTES + 64 * 1024
    pieces: bytearray = bytearray()
    pending: queue.Queue[bytes | None] = queue.Queue(maxsize=4)
    stop_reader = threading.Event()
    process = None
    worker = None
    def read_stdout() -> None:
        try:
            assert process is not None and process.stdout is not None
            while not stop_reader.is_set():
                chunk = process.stdout.read(32768)
                while not stop_reader.is_set():
                    try:
                        pending.put(chunk, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                if not chunk:
                    break
        except (OSError, ValueError):
            while not stop_reader.is_set():
                try:
                    pending.put(None, timeout=0.1)
                    break
                except queue.Full:
                    continue

    try:
        process = subprocess.Popen(
            ["git", *flags, "-C", str(repo), *args], stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, shell=False,
            env=env, bufsize=0)
        worker = threading.Thread(target=read_stdout, name="raif-git-bounded-reader", daemon=True)
        worker.start()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReviewBlocked("GIT_NOT_AVAILABLE_OR_TIMEOUT")
            try:
                block = pending.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue
            if block is None:
                raise ReviewBlocked("GIT_STREAM_READ_FAILED")
            if not block:
                break
            if len(pieces) + len(block) > limit:
                raise ReviewBlocked("GIT_OUTPUT_LIMIT")
            pieces.extend(block)
        if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
            raise ReviewBlocked("GIT_COMMAND_REJECTED")
        return bytes(pieces)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReviewBlocked("GIT_NOT_AVAILABLE_OR_TIMEOUT") from exc
    finally:
        stop_reader.set()
        if process is not None:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError:
                    pass
        if worker is not None:
            worker.join(timeout=1)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_atomic(path: Path, value: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex[:8])
    with tmp.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _json(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _log(run: Path, stage: str, verdict: str, code: str) -> None:
    # Only controlled enum-like codes; never external stdout/stderr, tokens or diff text.
    clean = lambda s: bool(re.fullmatch(r"[A-Z0-9_\-]{1,70}", s))
    if not all(map(clean, (stage, verdict, code))):
        raise ReviewBlocked("UNSAFE_AUDIT_FIELD")
    line = json.dumps({"utc": _utc(), "stage": stage, "verdict": verdict,
                       "code": code}, separators=(",", ":")) + "\n"
    with (run / "STAGES.jsonl").open("ab") as output:
        output.write(line.encode("utf-8"))
        output.flush()
        os.fsync(output.fileno())


def _checkpoint(run: Path, stage: str, verdict: str, cursor: str, evidence: dict) -> None:
    body = {"schema": "RAI_FABRIC_WORKTREE_CHECKPOINT/1", "stage": stage,
            "verdict": verdict, "cursor": cursor, "utc": _utc(), "evidence": evidence,
            "model_turn_count": 0, "git_push_count": 0, "git_merge_count": 0,
            "ci_jobs_triggered_by_tool": 0, "host_os": "Windows"}
    body["sha256"] = sha256(_json(body))
    _write_atomic(run / "CHECKPOINT.json", _json(body))


def _reject_duplicate_json_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate manifest key")
        result[name] = value
    return result


def _manifest(run: Path) -> dict:
    try:
        data = json.loads((run / "MANIFEST.json").read_text(encoding="utf-8"),
                          object_pairs_hook=_reject_duplicate_json_fields)
    except (ValueError, OSError) as exc:
        raise ReviewBlocked("MANIFEST_MISSING_OR_INVALID") from exc
    if not isinstance(data, dict):
        raise ReviewBlocked("MANIFEST_SCHEMA_INVALID")
    stamp = data.pop("manifest_sha256", None)
    if not isinstance(stamp, str) or stamp != sha256(_json(data)):
        raise ReviewBlocked("MANIFEST_INTEGRITY_FAILURE")
    data["manifest_sha256"] = stamp
    return data


def _source_repository(repo: Path, pin: str) -> Path:
    if not PIN.fullmatch(pin):
        raise ReviewBlocked("PIN_SHA_INVALID")
    repo = repo.absolute()
    _assert_local_volume(repo)
    _assert_no_reparse(repo)
    if not repo.is_dir() or not (repo / ".git").is_dir():
        raise ReviewBlocked("SOURCE_MUST_BE_GIT_CLONE")
    canonical = Path(os.fsdecode(_git(repo, "rev-parse", "--show-toplevel")).strip()).resolve()
    if canonical != repo.resolve():
        raise ReviewBlocked("SOURCE_TOPLEVEL_MISMATCH")
    if _git(repo, "rev-parse", "HEAD").decode("ascii").strip().lower() != pin.lower():
        raise ReviewBlocked("SOURCE_HEAD_NOT_PINNED")
    if _git(repo, "rev-parse", "--is-bare-repository").strip() != b"false":
        raise ReviewBlocked("BARE_REPOSITORY_BLOCKED")
    if _git(repo, "cat-file", "-t", pin).strip() != b"commit":
        raise ReviewBlocked("PIN_NOT_COMMIT")
    # Worktree checkout can invoke Git clean/smudge/process filters. Refuse all
    # repository .gitattributes and .gitmodules, including nested files.
    tree_paths = _git(repo, "ls-tree", "-r", "--name-only", "-z", pin)
    for raw_path in tree_paths.split(b"\0"):
        if raw_path and raw_path.rsplit(b"/", 1)[-1].lower() in (b".gitattributes", b".gitmodules"):
            raise ReviewBlocked("CHECKOUT_ATTR_OR_SUBMODULE_BLOCKED")
    git_info_attrs = repo / ".git" / "info" / "attributes"
    if git_info_attrs.exists() and git_info_attrs.stat().st_size:
        raise ReviewBlocked("CHECKOUT_INFO_ATTRIBUTES_BLOCKED")
    return repo


def prepare(repo: Path, pin: str, output_root: Path, allowlist: list[str]) -> Path:
    """Create a fresh detached Git worktree at a verified local commit, no fetch."""
    _windows_only()
    allow = _allowed(allowlist)
    repo = _source_repository(repo, pin)
    root = output_root.absolute()
    _assert_local_volume(root)
    _assert_no_reparse(root)
    if root == repo or repo in root.parents or root in repo.parents:
        raise ReviewBlocked("OUTPUT_OVERLAPS_SOURCE")
    root.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse(root)
    run = root / ("RAIF_10_1_" + uuid.uuid4().hex[:12])
    run.mkdir()
    (run / "empty_hooks").mkdir()
    worktree = run / "workspace"
    _log(run, "SOURCE_PIN", "PASS", "LOCAL_COMMIT_SHA_MATCH")
    try:
        # git uses only locally present objects; post-checkout hooks are disabled.
        _git(repo, "worktree", "add", "--detach", str(worktree), pin,
             timeout=60, hooks=run / "empty_hooks")
        _assert_no_reparse(worktree)
        if _git(worktree, "rev-parse", "HEAD").decode("ascii").strip().lower() != pin.lower():
            raise ReviewBlocked("WORKTREE_SHA_DRIFT")
        if _git(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
            raise ReviewBlocked("WORKTREE_NOT_CLEAN")
        data = {"schema": "RAI_FABRIC_WORKTREE_MANIFEST/1", "repo": str(repo),
                "pin_sha": pin.lower(), "worktree": str(worktree),
                "allowlist": allow, "run_id": run.name, "created_utc": _utc(),
                "explicit_human_review_required": True, "offline_only": True}
        data["manifest_sha256"] = sha256(_json(data))
        _write_atomic(run / "MANIFEST.json", _json(data))
        _log(run, "WORKTREE_CREATED", "PASS", "DETACHED_ISOLATED")
        _checkpoint(run, "WORKTREE_PREPARED", "PENDING_REVIEW", NEXT_REVIEW,
                    {"pin_sha": pin.lower(), "allowed_count": len(allow)})
        return run
    except ReviewBlocked as exc:
        _log(run, "WORKTREE_CREATED", "BLOCKED", exc.code)
        _checkpoint(run, "WORKTREE_PREPARED", "BLOCKED", NEXT_REVIEW,
                    {"code": exc.code})
        # Never auto-force-remove: preserve evidence and worktree for operator review.
        raise


def _changed(repo: Path) -> list[str]:
    raw = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    items = raw.split(b"\0")
    if items[-1] != b"":
        raise ReviewBlocked("STATUS_STREAM_MALFORMED")
    changed = []
    for item in items[:-1]:
        if len(item) < 4 or item[2:3] != b" ":
            raise ReviewBlocked("STATUS_STREAM_MALFORMED")
        state = item[:2]
        # Staged content may differ from reviewed worktree bytes; reject it.
        # Renames, copies, deletions, conflicts and mode changes also fail closed.
        if state[:1] not in (b" ", b"?"):
            raise ReviewBlocked("INDEX_MUTATION_BLOCKED")
        if state not in (b"??", b" M"):
            raise ReviewBlocked("UNSUPPORTED_GIT_CHANGE")
        try:
            rel = item[3:].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ReviewBlocked("PATH_ENCODING_INVALID") from exc
        changed.append(_strict_path(rel))
    return changed


def _safe_text(data: bytes) -> str:
    if b"\0" in data or len(data) > MAX_FILE_BYTES:
        raise ReviewBlocked("BINARY_OR_FILE_SIZE_BLOCKED")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReviewBlocked("NON_UTF8_FILE_BLOCKED") from exc
    if any((ord(ch) < 32 and ch not in "\n\r\t") or ord(ch) == 127 for ch in text):
        raise ReviewBlocked("CONTROL_CHAR_BLOCKED")
    if any(marker.search(text) for marker in SECRET_MARKERS):
        raise ReviewBlocked("POTENTIAL_SECRET_BLOCKED")
    return text


def _verify_mock(run: Path, files: dict[str, bytes]) -> int:
    data = _manifest(run)
    if data["allowlist"] != [MOCK_PATH] or set(files) != {MOCK_PATH}:
        raise ReviewBlocked("MOCK_FILESET_MISMATCH")
    if files[MOCK_PATH] != MOCK_SOURCE.encode("utf-8"):
        raise ReviewBlocked("MOCK_SOURCE_NOT_IDENTICAL")
    parsed = ast.parse(MOCK_SOURCE)
    if len(parsed.body) != 1 or not isinstance(parsed.body[0], ast.FunctionDef):
        raise ReviewBlocked("MOCK_AST_REJECTED")
    scope = {"__builtins__": {}}
    exec(compile(parsed, "<offline-owned-mock>", "exec"), scope)
    checks = ((2, 3, 5), (0, 7, 7), (-2, -4, -6))
    if not all(scope["add"](a, b) == expected for a, b, expected in checks):
        raise ReviewBlocked("MOCK_TEST_FAILED")
    return len(checks)


def review(run: Path, *, run_mock_tests: bool = False) -> dict:
    """Reject unsafe changes; write reviewable local patch without committing anything."""
    _windows_only()
    run = run.absolute()
    _assert_local_volume(run)
    _assert_no_reparse(run)
    manifest = _manifest(run)
    if manifest.get("schema") != "RAI_FABRIC_WORKTREE_MANIFEST/1" or manifest.get("run_id") != run.name:
        raise ReviewBlocked("MANIFEST_ID_INVALID")
    if not all(isinstance(manifest.get(name), str) for name in ("worktree", "repo", "pin_sha")):
        raise ReviewBlocked("MANIFEST_SCHEMA_INVALID")
    if not isinstance(manifest.get("allowlist"), list):
        raise ReviewBlocked("MANIFEST_SCHEMA_INVALID")
    worktree = Path(manifest["worktree"])
    repo = Path(manifest["repo"])
    pin = manifest["pin_sha"]
    if worktree != run / "workspace" or not PIN.fullmatch(pin):
        raise ReviewBlocked("WORKTREE_MANIFEST_PATH_MISMATCH")
    _assert_no_reparse(repo)
    _assert_no_reparse(worktree)
    if not worktree.is_dir() or not repo.is_dir():
        raise ReviewBlocked("WORKTREE_MISSING")
    if not (repo / ".git").is_dir():
        raise ReviewBlocked("SOURCE_GIT_DIR_MISSING")
    common = Path(_git(worktree, "rev-parse", "--git-common-dir").decode("utf-8").strip())
    if not common.is_absolute():
        common = worktree / common
    if common.resolve() != (repo / ".git").resolve():
        raise ReviewBlocked("WORKTREE_OWNER_DRIFT")
    if Path(_git(worktree, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve() != worktree.resolve():
        raise ReviewBlocked("WORKTREE_TOPLEVEL_DRIFT")
    if _git(worktree, "rev-parse", "HEAD").decode("ascii").strip().lower() != pin:
        raise ReviewBlocked("WORKTREE_SHA_DRIFT")
    if _git(worktree, "rev-parse", "--abbrev-ref", "HEAD").strip() != b"HEAD":
        raise ReviewBlocked("WORKTREE_NOT_DETACHED")
    # Check .git worktree pointer (ordinary text file) and forbid nested links.
    if not (worktree / ".git").is_file() or _is_reparse(worktree / ".git"):
        raise ReviewBlocked("WORKTREE_GIT_POINTER_INVALID")
    allowed = _allowed(manifest["allowlist"])
    changed = _changed(worktree)
    if not changed or len(changed) > MAX_FILES or len(set(x.casefold() for x in changed)) != len(changed):
        raise ReviewBlocked("CHANGE_COUNT_OR_COLLISION")
    if set(changed) - set(allowed):
        raise ReviewBlocked("OUT_OF_ALLOWLIST")
    if _git(worktree, "ls-files", "--others", "--ignored", "--exclude-standard", "-z"):
        raise ReviewBlocked("IGNORED_FILES_PRESENT")
    files: dict[str, bytes] = {}
    patches: list[str] = []
    total = 0
    for rel in sorted(changed):
        target = worktree.joinpath(*rel.split("/"))
        _assert_no_reparse(target)
        if not target.is_file() or not stat.S_ISREG(target.lstat().st_mode):
            raise ReviewBlocked("NOT_A_REGULAR_FILE")
        if target.stat().st_nlink != 1:
            raise ReviewBlocked("HARDLINK_BLOCKED")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise ReviewBlocked("FILE_SIZE_LIMIT")
        new = target.read_bytes()
        total += len(new)
        if total > MAX_TOTAL_BYTES:
            raise ReviewBlocked("TOTAL_SIZE_LIMIT")
        new_text = _safe_text(new)
        index = _git(worktree, "ls-files", "-s", "--", rel)
        if index:
            for entry in index.splitlines():
                if not entry.startswith((b"100644 ", b"100755 ")):
                    raise ReviewBlocked("INDEX_MODE_BLOCKED")
        old_index = _git(worktree, "ls-tree", pin, "--", rel).splitlines()
        if old_index:
            if len(old_index) != 1 or not old_index[0].startswith((b"100644 ", b"100755 ")):
                raise ReviewBlocked("BASELINE_MODE_BLOCKED")
            old = _git(worktree, "show", f"{pin}:{rel}")
            old_text = _safe_text(old)
        else:
            old_text = ""
        files[rel] = new
        lines = list(difflib.unified_diff(old_text.splitlines(keepends=True),
                                          new_text.splitlines(keepends=True),
                                          fromfile=f"a/{rel}" if old_index else "/dev/null",
                                          tofile=f"b/{rel}", lineterm="\n"))
        patches.append(f"diff --git a/{rel} b/{rel}\n" + "".join(lines))
    patch = "".join(patches).encode("utf-8")
    if not patch or len(patch) > MAX_PATCH_BYTES:
        raise ReviewBlocked("PATCH_EMPTY_OR_TOO_LARGE")
    if run_mock_tests:
        tests_passed = _verify_mock(run, files)
    else:
        tests_passed = 0
    # Recheck after the complete review to catch file/index changes in-flight.
    if _changed(worktree) != changed:
        raise ReviewBlocked("STATUS_RACE_DETECTED")
    for rel, old_bytes in files.items():
        target = worktree.joinpath(*rel.split("/"))
        _assert_no_reparse(target)
        if not target.is_file() or target.stat().st_nlink != 1 or target.read_bytes() != old_bytes:
            raise ReviewBlocked("FILE_RACE_DETECTED")
    # Patch is not stored until every allowlist, type, size, secret and mock check passes.
    _write_atomic(run / "REVIEW.patch", patch)
    evidence = {"pin_sha": pin, "changed_paths": sorted(files),
                "file_sha256": {name: sha256(data) for name, data in files.items()},
                "review_patch_sha256": sha256(patch), "review_patch_bytes": len(patch),
                "mock_tests_passed": tests_passed, "manual_merge_gate": True}
    _log(run, "ALLOWLIST_REVIEW", "PASS", "SAFE_TEXT_ONLY")
    if run_mock_tests:
        _log(run, "OFFLINE_MOCK", "PASS", "THREE_DETERMINISTIC_TESTS")
    _checkpoint(run, "SAFE_DIFF_REVIEW", "PENDING_HUMAN_APPROVAL", NEXT_WINDOWS, evidence)
    return {"verdict": "PENDING_HUMAN_APPROVAL", "cursor": NEXT_WINDOWS,
            "run_dir": str(run), "changed_paths": len(files), "mock_tests_passed": tests_passed,
            "patch_sha256": sha256(patch)}


def offline_demo(repo: Path, pin: str, root: Path) -> dict:
    run = prepare(repo, pin, root, [MOCK_PATH])
    try:
        dest = run / "workspace" / "sandbox_demo"
        dest.mkdir(exist_ok=False)
        with (dest / "arithmetic.py").open("xb") as handle:
            handle.write(MOCK_SOURCE.encode("utf-8"))
        _log(run, "MOCK_CREATED", "PASS", "NO_MODEL_EXECUTION")
        return review(run, run_mock_tests=True)
    except ReviewBlocked as exc:
        _log(run, "SAFE_DIFF_REVIEW", "BLOCKED", exc.code)
        _checkpoint(run, "SAFE_DIFF_REVIEW", "BLOCKED", NEXT_REVIEW, {"code": exc.code})
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RAiF 10.1: офлайн Git worktree, Windows")
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("prepare", help="Создать чистый worktree с pin SHA")
    demo = sub.add_parser("demo", help="Создать worktree и безопасную offline mock правку")
    check = sub.add_parser("review", help="Проанализировать созданный worktree без модели")
    for p in (make, demo):
        p.add_argument("--repo", type=Path, required=True)
        p.add_argument("--pin", required=True)
        p.add_argument("--output-root", type=Path, required=True)
    make.add_argument("--allow", action="append", required=True)
    check.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            result = offline_demo(args.repo, args.pin, args.output_root)
        elif args.command == "prepare":
            run = prepare(args.repo, args.pin, args.output_root, args.allow)
            result = {"verdict": "PREPARED", "cursor": NEXT_REVIEW, "run_dir": str(run)}
        else:
            result = review(args.run)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except ReviewBlocked as exc:
        if args.command == "review":
            try:
                run = args.run.absolute()
                _assert_local_volume(run)
                _assert_no_reparse(run)
                if (run.is_dir() and re.fullmatch(r"RAIF_10_1_[0-9a-f]{12}", run.name)
                        and (run / "MANIFEST.json").is_file()):
                    _log(run, "SAFE_DIFF_REVIEW", "BLOCKED", exc.code)
                    _checkpoint(run, "SAFE_DIFF_REVIEW", "BLOCKED", NEXT_REVIEW,
                                {"code": exc.code})
            except (OSError, ReviewBlocked):
                pass  # Never write logs into an untrusted/reparsed location.
        print(json.dumps({"verdict": "BLOCKED", "code": exc.code, "cursor": NEXT_REVIEW},
                         sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
