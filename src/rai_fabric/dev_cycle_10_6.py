"""10.6: офлайн-пакет задачи разработки на базе 10.1 worktree и FabricStore.

Только фиксированная synthetic-правка. Готовит запрос независимого ревью и
DRAFT-PR intent, но НЕ выдаёт QA/grant, НЕ пушит, НЕ публикует и НЕ сливает PR.
"""
from __future__ import annotations

__version__ = "0.1.0"

import json
import re
from pathlib import Path
from typing import Any

from .store import FabricError, FabricStore
from . import worktree_review as wt

SCHEMA = "RAIF_10_6_OFFLINE_CYCLE/1"
CURSOR = "RAIF/10_6_INDEPENDENT_QA_AND_DRAFT_PR_GATE"
TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
# The old C: checkout holds tracked WIP and must not be registered as a new worktree owner.
LEGACY_ROOT = "c:/git/rassvet_ai_fabric"


class CycleBlocked(FabricError):
    """Safe, constant error code rather than any external process output."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _is_legacy(path: str | Path) -> bool:
    return str(path).replace("\\", "/").rstrip("/").casefold() == LEGACY_ROOT


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        if len(raw) > 64 * 1024:
            raise ValueError("oversize")
        def unique(fields: list[tuple[str, Any]]) -> dict[str, Any]:
            values: dict[str, Any] = {}
            for key, value in fields:
                if key in values:
                    raise ValueError("duplicate")
                values[key] = value
            return values
        parsed = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=unique)
        if not isinstance(parsed, dict):
            raise ValueError("root")
        return parsed
    except (OSError, ValueError, UnicodeError) as exc:
        raise CycleBlocked("CYCLE_JSON_INVALID") from exc


def _stamp(value: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(value)
    sealed["sha256"] = wt.sha256(wt._json(value))
    return sealed


def _check_stamp(value: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("sha256", None)
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CycleBlocked("CYCLE_RECEIPT_SEAL_INVALID")
    if wt.sha256(wt._json(payload)) != digest:
        raise CycleBlocked("CYCLE_RECEIPT_SEAL_INVALID")
    return payload


def _check_task(store: FabricStore, task_id: str, repo: Path, pin: str,
                root: Path) -> None:
    wt._windows_only()
    if not isinstance(store, FabricStore) or not TASK_ID.fullmatch(task_id):
        raise CycleBlocked("DEVELOPMENT_TASK_INVALID")
    if not wt.PIN.fullmatch(pin) or pin != pin.lower():
        raise CycleBlocked("SOURCE_PIN_INVALID")
    if _is_legacy(repo) or _is_legacy(root) or _is_legacy(store.path):
        raise CycleBlocked("LEGACY_OWNER_CHECKOUT_FORBIDDEN")
    if repo.resolve() in store.path.resolve().parents or root.resolve() in store.path.resolve().parents:
        # Never put mutable queue or state inside the source checkout or staging root.
        raise CycleBlocked("QUEUE_DB_ISOLATION_REQUIRED")
    row = store.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if not row or row[0] != "1":
        raise CycleBlocked("LEGACY_MOCK_QUEUE_ONLY")
    task = store.get(task_id)
    if task["provider"] != "mock" or task["status"] != "QUEUED":
        raise CycleBlocked("NON_SYNTHETIC_OR_CLAIMED_TASK")
    if Path(task["workspace"]).resolve() != repo.resolve():
        raise CycleBlocked("TASK_REPOSITORY_MISMATCH")
    # Pure read-only preflight BEFORE leasing the task or creating a worktree.
    wt._source_repository(repo, pin)
    if wt._git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        raise CycleBlocked("SOURCE_REPOSITORY_DIRTY")
    wt._assert_local_volume(root.absolute())
    wt._assert_no_reparse(root.absolute())
    if root.resolve() == repo.resolve() or repo.resolve() in root.resolve().parents:
        raise CycleBlocked("OUTPUT_OVERLAPS_SOURCE")


def _build_evidence(run: Path, expected_pin: str) -> dict[str, Any]:
    manifest = wt._manifest(run)
    check = _read_json(run / "CHECKPOINT.json")
    _check_stamp(check)
    proof = check.get("evidence")
    if (manifest.get("schema") != "RAI_FABRIC_WORKTREE_MANIFEST/1"
            or manifest.get("pin_sha") != expected_pin
            or manifest.get("allowlist") != [wt.MOCK_PATH]
            or check.get("verdict") != "PENDING_HUMAN_APPROVAL"
            or check.get("stage") != "SAFE_DIFF_REVIEW"
            or not isinstance(proof, dict)
            or proof.get("pin_sha") != expected_pin
            or proof.get("changed_paths") != [wt.MOCK_PATH]
            or proof.get("mock_tests_passed") != 3
            or proof.get("manual_merge_gate") is not True
            or check.get("model_turn_count") != 0
            or check.get("git_push_count") != 0
            or check.get("git_merge_count") != 0):
        raise CycleBlocked("REVIEW_PROOF_NOT_ADMITTED")
    patch = run / "REVIEW.patch"
    worktree_file = run / "workspace" / wt.MOCK_PATH
    if not patch.is_file() or not worktree_file.is_file():
        raise CycleBlocked("REVIEW_FILE_MISSING")
    actual_patch_sha = wt.sha256(patch.read_bytes())
    source_sha = wt.sha256(worktree_file.read_bytes())
    if (proof.get("review_patch_sha256") != actual_patch_sha
            or proof.get("file_sha256") != {wt.MOCK_PATH: source_sha}
            or worktree_file.read_bytes() != wt.MOCK_SOURCE.encode("utf-8")):
        raise CycleBlocked("SOURCE_OR_PATCH_SHA_DRIFT")
    repo = Path(manifest["repo"])
    wt._source_repository(repo, expected_pin)
    if wt._git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        raise CycleBlocked("SOURCE_REPOSITORY_DIRTY")
    return {
        "base_sha": expected_pin,
        "changed_paths": [wt.MOCK_PATH],
        "patch_sha256": actual_patch_sha,
        "file_sha256": {wt.MOCK_PATH: source_sha},
        "mock_tests_passed": 3,
        "model_calls": 0, "external_provider_calls": 0,
        "git_push_count": 0, "git_merge_count": 0,
    }


def run_synthetic_cycle(store: FabricStore, task_id: str, repo: Path, pin: str,
                        output_root: Path, *, owner: str = "raif-10-6-synthetic") -> dict[str, Any]:
    """Single allowlisted dev task -> isolated diff -> 3 checks -> QA/PR intent.

    The return is NOT evidence of independent review or permission to publish PR.
    """
    repo, root = Path(repo), Path(output_root)
    _check_task(store, task_id, repo, pin, root)
    if not isinstance(owner, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", owner):
        raise CycleBlocked("EXECUTOR_OWNER_INVALID")
    claim = store.claim(owner, provider="mock", task_id=task_id, lease_seconds=240)
    if not claim or claim["task_id"] != task_id:
        raise CycleBlocked("DEVELOPMENT_TASK_NOT_READY")
    token = claim["lease_token"]
    try:
        result = wt.offline_demo(repo, pin, root)
        if result.get("verdict") != "PENDING_HUMAN_APPROVAL" or result.get("mock_tests_passed") != 3:
            raise CycleBlocked("SYNTHETIC_REVIEW_BLOCKED")
        run = Path(result["run_dir"])
        evidence = _build_evidence(run, pin)
        task = _stamp({
            "schema": SCHEMA, "task_id": task_id, "recipe": "OWNED_MOCK_ADD_V1",
            "run_id": run.name, "objective_sha256": wt.sha256(
                store.get(task_id)["objective"].encode("utf-8")),
            "source_repo_basename": repo.name,
            **evidence,
        })
        qa = _stamp({
            "schema": "RAIF_10_6_QA_REQUEST/1", "task_id": task_id,
            "base_sha": pin, "patch_sha256": evidence["patch_sha256"],
            "changed_paths": evidence["changed_paths"],
            "automated_checks": "3_OF_3_SYNTHETIC_PASS",
            "reviewer_class_required": "EXTERNAL_INDEPENDENT_CLEAN_CONTEXT",
            "actual_independent_review": "NOT_PERFORMED",
            "required_results": ["exact SHA/diff binding", "semantic counterexamples", "independent verdict"],
            "merge_gate": "CLOSED",
        })
        draft = _stamp({
            "schema": "RAIF_10_6_DRAFT_PR_INTENT/1", "task_id": task_id,
            "base_sha": pin, "patch_sha256": evidence["patch_sha256"],
            "branch_committed": False, "remote_pr_created": False,
            "pr_kind": "DRAFT_ONLY", "publication_authorized": False,
            "merge_authorized": False, "independent_qa": "PENDING",
            "external_provider_calls": 0,
        })
        records = {"DEV_TASK.json": task, "QA_REQUEST.json": qa,
                   "DRAFT_PR_INTENT.json": draft}
        for filename, item in records.items():
            wt._write_atomic(run / filename, wt._json(item))
        receipt = _stamp({
            "schema": "RAIF_10_6_CYCLE_RECEIPT/1", "task_id": task_id,
            "base_sha": pin, "run_id": run.name,
            "status": "REVIEW_PACKAGE_READY_QA_PENDING",
            "artifacts_sha256": {name: wt.sha256(wt._json(item))
                                 for name, item in records.items()},
            "model_turn_count": 0, "push_count": 0, "merge_count": 0,
            "next_cursor": CURSOR,
        })
        wt._write_atomic(run / "CYCLE_RECEIPT.json", wt._json(receipt))
        store.checkpoint(task_id, owner, token,
                         "OFFLINE_DEVELOPMENT_PACKAGE", CURSOR,
                         {"patch_sha256": evidence["patch_sha256"],
                          "mock_tests_passed": 3, "independent_qa": "PENDING",
                          "run_id": run.name}, verdict="PARTIAL")
        status = store.finish(task_id, owner, token, verdict="PASS",
                              response="Синтетический пакет готов; независимая QA и публикация PR не выполнялись",
                              evidence={"simulation": True, "external_model_calls": 0,
                                        "scope": "OFFLINE_PACKAGE_ONLY",
                                        "pr_created": False}, cursor=CURSOR)
        return {"verdict": "PACKAGE_READY_QA_PENDING", "task_status": status["status"],
                "task_id": task_id, "run_dir": str(run), "patch_sha256": evidence["patch_sha256"],
                "mock_tests_passed": 3, "independent_qa": "NOT_PERFORMED",
                "pr_created": False, "merge_authorized": False, "cursor": CURSOR}
    except Exception as exc:
        code = exc.code if isinstance(exc, (wt.ReviewBlocked, CycleBlocked)) else "DEV_CYCLE_EXECUTION_FAILED"
        try:
            store.finish(task_id, owner, token, verdict="BLOCKED",
                         response="10.6: synthetic stage blocked; no automatic retry",
                         evidence={"simulation": True, "reason_code": code},
                         cursor="RAIF/10_6_MANUAL_RECONCILIATION")
        except FabricError:
            # The lease may already have expired: only recovery may reconcile.
            pass
        if isinstance(exc, CycleBlocked):
            raise
        raise CycleBlocked(code) from exc


def verify_cycle_receipt(run_dir: Path) -> dict[str, Any]:
    """Readback only, no review authority; refuses tampered/missing records."""
    wt._windows_only()
    run = Path(run_dir).absolute()
    wt._assert_local_volume(run)
    wt._assert_no_reparse(run)
    rec = _read_json(run / "CYCLE_RECEIPT.json")
    raw = _check_stamp(rec)
    if raw.get("schema") != "RAIF_10_6_CYCLE_RECEIPT/1" or raw.get("run_id") != run.name:
        raise CycleBlocked("CYCLE_RECEIPT_WRONG_IDENTITY")
    hashes = raw.get("artifacts_sha256")
    if not isinstance(hashes, dict) or set(hashes) != {
            "DEV_TASK.json", "QA_REQUEST.json", "DRAFT_PR_INTENT.json"}:
        raise CycleBlocked("CYCLE_ARTIFACT_SET_INVALID")
    for name, expected in hashes.items():
        item = _read_json(run / name)
        _check_stamp(item)
        if wt.sha256(wt._json(item)) != expected:
            raise CycleBlocked("CYCLE_ARTIFACT_SHA_MISMATCH")
        if item.get("base_sha") != raw["base_sha"] or item.get("task_id") != raw["task_id"]:
            raise CycleBlocked("CYCLE_ARTIFACT_BINDING_MISMATCH")
    evidence = _build_evidence(run, raw["base_sha"])
    task = _read_json(run / "DEV_TASK.json")
    qa = _read_json(run / "QA_REQUEST.json")
    draft = _read_json(run / "DRAFT_PR_INTENT.json")
    if (task.get("patch_sha256") != evidence["patch_sha256"]
            or qa.get("patch_sha256") != evidence["patch_sha256"]
            or draft.get("patch_sha256") != evidence["patch_sha256"]
            or qa.get("actual_independent_review") != "NOT_PERFORMED"
            or draft.get("publication_authorized") is not False
            or draft.get("merge_authorized") is not False
            or draft.get("remote_pr_created") is not False):
        raise CycleBlocked("CYCLE_QA_OR_PROMOTION_GATE_DRIFT")
    return {"verdict": "READBACK_PASS_QA_PENDING", "task_id": raw["task_id"],
            "base_sha": raw["base_sha"], "patch_sha256": evidence["patch_sha256"],
            "mock_tests_passed": 3, "independent_qa": "NOT_PERFORMED",
            "publication_authorized": False, "merge_authorized": False}
