"""CP-54D: offline checkpoint integrity and non-replaying resume planner.

This deliberately cannot execute a task. A committed, pending or unknown
external effect must never be replayed without separate human review.
All input metadata are constrained and cannot contain credential material.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_ID = re.compile(r"task-[0-9a-f]{12}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_CURSOR = re.compile(r"[A-Z0-9_./-]{4,120}\Z")
_MAX_BYTES = 4096
_FILENAME = "TASK_CHECKPOINT.json"


class ContinuityError(ValueError):
    """Fixed safe error codes only."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SideEffect(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"
    COMMITTED = "COMMITTED"


@dataclass(frozen=True)
class ContinuityRecord:
    task_id: str
    git_sha: str
    cursor: str
    generation: int
    effect: SideEffect

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not _ID.fullmatch(self.task_id):
            raise ContinuityError("TASK_ID_INVALID")
        if not isinstance(self.git_sha, str) or not _SHA.fullmatch(self.git_sha):
            raise ContinuityError("REPOSITORY_SHA_INVALID")
        if (not isinstance(self.cursor, str) or not _CURSOR.fullmatch(self.cursor)
                or ".." in self.cursor or self.cursor.startswith("/")):
            raise ContinuityError("CURSOR_INVALID")
        if type(self.generation) is not int or not 0 <= self.generation < 2**32:
            raise ContinuityError("GENERATION_INVALID")
        if type(self.effect) is not SideEffect:
            raise ContinuityError("EFFECT_STATE_INVALID")

    def body(self) -> dict:
        return {"schema": "RAIF_CONTINUITY/1", "task_id": self.task_id,
                "git_sha": self.git_sha, "cursor": self.cursor,
                "generation": self.generation, "effect": self.effect.value}


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def serialize_checkpoint(record: ContinuityRecord) -> bytes:
    if not isinstance(record, ContinuityRecord):
        raise ContinuityError("CHECKPOINT_RECORD_INVALID")
    payload = record.body()
    outer = {"payload": payload, "sha256": hashlib.sha256(_canonical(payload)).hexdigest()}
    encoded = _canonical(outer) + b"\n"
    if len(encoded) > _MAX_BYTES:
        raise ContinuityError("CHECKPOINT_SIZE_INVALID")
    return encoded


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ContinuityError("CHECKPOINT_DUPLICATE_KEY")
        obj[key] = value
    return obj


def parse_checkpoint(encoded: bytes) -> ContinuityRecord:
    if not isinstance(encoded, bytes) or not 0 < len(encoded) <= _MAX_BYTES:
        raise ContinuityError("CHECKPOINT_SIZE_INVALID")
    def _reject_constant(_value: str) -> object:
        raise ContinuityError("CHECKPOINT_JSON_INVALID")

    try:
        doc = json.loads(encoded.decode("ascii"), object_pairs_hook=_no_duplicate_keys,
                         parse_constant=_reject_constant)
    except ContinuityError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise ContinuityError("CHECKPOINT_JSON_INVALID") from None
    if not isinstance(doc, dict) or set(doc) != {"payload", "sha256"}:
        raise ContinuityError("CHECKPOINT_SCHEMA_INVALID")
    payload, checksum = doc["payload"], doc["sha256"]
    if not isinstance(payload, dict) or set(payload) != {"schema", "task_id", "git_sha", "cursor", "generation", "effect"}:
        raise ContinuityError("CHECKPOINT_SCHEMA_INVALID")
    if payload["schema"] != "RAIF_CONTINUITY/1":
        raise ContinuityError("CHECKPOINT_SCHEMA_INVALID")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ContinuityError("CHECKPOINT_HASH_INVALID")
    if not hmac.compare_digest(hashlib.sha256(_canonical(payload)).hexdigest(), checksum):
        raise ContinuityError("CHECKPOINT_HASH_MISMATCH")
    try:
        effect = SideEffect(payload["effect"])
        return ContinuityRecord(payload["task_id"], payload["git_sha"],
                                payload["cursor"], payload["generation"], effect)
    except (KeyError, ValueError, TypeError):
        raise ContinuityError("CHECKPOINT_FIELDS_INVALID") from None


def plan_resume(record: ContinuityRecord, *, operator_approved: bool = False) -> dict:
    """Only create a plan. No task replay, credential access or Git mutation."""
    if not isinstance(record, ContinuityRecord):
        raise ContinuityError("CHECKPOINT_RECORD_INVALID")
    if record.effect is not SideEffect.NONE:
        verdict = "BLOCKED_PENDING_REVIEW"
    elif operator_approved is True:
        verdict = "PLAN_READY_MANUAL_EXECUTION"
    else:
        verdict = "AWAIT_OPERATOR_APPROVAL"
    return {"verdict": verdict, "cursor": record.cursor,
            "task_execution_performed": False, "external_effect_replayed": False,
            "authority_changed": False}


def _validate_directory(path: Path) -> None:
    """Reject symlink/junction ancestors, not only the final directory.

    This is a static preflight, not a claim of race-free Windows handle binding.
    A separately trusted caller must own the directory and prevent renames.
    """
    if not path.is_dir():
        raise ContinuityError("CHECKPOINT_DIRECTORY_UNSAFE")
    current = path.absolute()
    while True:
        try:
            meta = current.lstat()
        except OSError:
            raise ContinuityError("CHECKPOINT_DIRECTORY_UNSAFE") from None
        if (stat.S_ISLNK(meta.st_mode)
                or getattr(meta, "st_file_attributes", 0) & 0x400):
            raise ContinuityError("CHECKPOINT_DIRECTORY_UNSAFE")
        if current.parent == current:
            break
        current = current.parent


def persist_checkpoint(directory: Path, record: ContinuityRecord) -> None:
    """Atomically write within an explicitly caller-chosen local test directory.

    Do not use on an authority or user workspace; this function never creates
    directories and does not follow destination symlinks.
    """
    root = Path(directory)
    _validate_directory(root)
    destination = root / _FILENAME
    if destination.is_symlink():
        raise ContinuityError("CHECKPOINT_SYMLINK_BLOCKED")
    if destination.exists() and not destination.is_file():
        raise ContinuityError("CHECKPOINT_TARGET_UNSAFE")
    # os.mkdir is atomic on a local filesystem. A stale crash lock is not
    # automatically stolen: human-controlled recovery must resolve it.
    lock = root / ".raif-continuity.lock"
    try:
        lock.mkdir()
    except OSError:
        raise ContinuityError("CHECKPOINT_WRITER_BUSY") from None
    temporary = root / (".raif-task-" + uuid.uuid4().hex + ".tmp")
    try:
        if destination.exists():
            prior = load_checkpoint(root)
            if record.task_id != prior.task_id or record.git_sha != prior.git_sha:
                raise ContinuityError("CHECKPOINT_LINEAGE_MISMATCH")
            if record.generation <= prior.generation:
                raise ContinuityError("CHECKPOINT_GENERATION_NOT_MONOTONIC")
            # A checksum is not a review receipt. Once external effects are
            # possible, changing their state could launder a blocked task.
            if prior.effect is not SideEffect.NONE and record.effect is not prior.effect:
                raise ContinuityError("CHECKPOINT_EFFECT_TRANSITION_REQUIRES_REVIEW")
        raw = serialize_checkpoint(record)
        try:
            with temporary.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except OSError:
            raise ContinuityError("CHECKPOINT_WRITE_FAILED") from None
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    finally:
        try:
            lock.rmdir()
        except OSError:
            # Never falsely claim recovery; crash/stale lock remains BLOCKED.
            pass


def load_checkpoint(directory: Path) -> ContinuityRecord:
    root = Path(directory)
    _validate_directory(root)
    path = root / _FILENAME
    try:
        meta = path.lstat()
        if not stat.S_ISREG(meta.st_mode) or path.is_symlink() or meta.st_size > _MAX_BYTES:
            raise ContinuityError("CHECKPOINT_FILE_UNSAFE")
        with path.open("rb") as stream:
            raw = stream.read(_MAX_BYTES + 1)
    except ContinuityError:
        raise
    except OSError:
        raise ContinuityError("CHECKPOINT_READ_FAILED") from None
    return parse_checkpoint(raw)
