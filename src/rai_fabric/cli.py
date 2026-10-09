"""Explicit local control surface; prompts/tokens are never silently sent to an API."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .gateway import Gateway
from .mcp_server import MCPStdioServer
from .store import FabricError, FabricStore
from .worker import run_one


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rai", description="Rassvet AI Fabric v0.1.0 (from scratch)")
    p.add_argument("--db", required=True, help="Dedicated SQLite store path; never point into BPR40/Codex storage")
    subs = p.add_subparsers(dest="action", required=True)
    subs.add_parser("init", help="Explicitly initialize an isolated task database")
    cmd = subs.add_parser("submit")
    cmd.add_argument("--objective", required=True)
    cmd.add_argument("--provider", choices=["mock", "antigravity", "codex-app"], default="mock")
    cmd.add_argument("--workspace", required=True)
    cmd.add_argument("--task-id")
    cmd.add_argument("--depends-on", action="append", default=[])
    cmd = subs.add_parser("tasks")
    cmd.add_argument("--limit", type=int, default=50)
    cmd = subs.add_parser("task")
    cmd.add_argument("id")
    cmd = subs.add_parser("events")
    cmd.add_argument("id")
    cmd = subs.add_parser("claim")
    cmd.add_argument("--owner", required=True)
    cmd.add_argument("--provider", choices=["mock", "antigravity", "codex-app"])
    cmd.add_argument("--lease-seconds", type=int, default=120)
    cmd = subs.add_parser("heartbeat")
    cmd.add_argument("id")
    cmd.add_argument("--owner", required=True)
    cmd.add_argument("--lease-seconds", type=int, default=120)
    cmd = subs.add_parser("checkpoint")
    cmd.add_argument("id")
    cmd.add_argument("--owner", required=True)
    cmd.add_argument("--stage", required=True)
    cmd.add_argument("--cursor", required=True)
    cmd.add_argument("--verdict", choices=["PASS", "PARTIAL", "BLOCKED"], default="PARTIAL")
    cmd.add_argument("--evidence", default="{}", help="JSON object")
    cmd = subs.add_parser("finish")
    cmd.add_argument("id")
    cmd.add_argument("--owner", required=True)
    cmd.add_argument("--verdict", choices=["PASS", "PARTIAL", "BLOCKED"], required=True)
    cmd.add_argument("--response", required=True)
    cmd.add_argument("--cursor", default="REVIEW")
    cmd.add_argument("--evidence", default="{}")
    cmd = subs.add_parser("result")
    cmd.add_argument("id")
    subs.add_parser("recover")
    cmd = subs.add_parser("requeue")
    cmd.add_argument("id")
    cmd.add_argument("--acknowledge", required=True)
    cmd = subs.add_parser("cancel")
    cmd.add_argument("id")
    cmd = subs.add_parser("confirm-cancel")
    cmd.add_argument("id")
    cmd.add_argument("--owner", required=True)
    cmd = subs.add_parser("run-once")
    cmd.add_argument("--provider", choices=["mock", "antigravity", "codex-app"], required=True)
    cmd.add_argument("--allow-external", action="store_true")
    cmd.add_argument("--timeout", type=int, default=300)
    cmd = subs.add_parser("mcp")
    cmd.add_argument("--workspace", required=True)
    return p


def _evidence(value: str) -> dict[str, Any]:
    data = json.loads(value)
    if not isinstance(data, dict):
        raise FabricError("Evidence must be JSON object")
    return data


def _token() -> str:
    # Do not pass lease credentials in process command-line arguments.
    value = os.environ.get("RAI_LEASE_TOKEN", "")
    if not value:
        raise FabricError("RAI_LEASE_TOKEN environment variable is required")
    return value


def run(argv: list[str] | None = None) -> Any:
    a = parser().parse_args(argv)
    with FabricStore(a.db, initialize=(a.action == "init")) as s:
        if a.action == "init":
            return {"initialized": True, "database": str(s.path), "schema_version": 1}
        if a.action == "submit":
            return s.submit(a.objective, a.provider, a.workspace,
                            task_id=a.task_id, depends_on=a.depends_on)
        if a.action == "tasks":
            return {"tasks": s.list(a.limit)}
        if a.action == "task":
            return s.get(a.id)
        if a.action == "events":
            return {"events": s.events(a.id)}
        if a.action == "result":
            return s.result(a.id)
        if a.action == "claim":
            return s.claim(a.owner, provider=a.provider, lease_seconds=a.lease_seconds)
        if a.action == "heartbeat":
            return s.heartbeat(a.id, a.owner, _token(), lease_seconds=a.lease_seconds)
        if a.action == "checkpoint":
            return s.checkpoint(a.id, a.owner, _token(), a.stage, a.cursor,
                                _evidence(a.evidence), a.verdict)
        if a.action == "finish":
            return s.finish(a.id, a.owner, _token(), verdict=a.verdict, response=a.response,
                            evidence=_evidence(a.evidence), cursor=a.cursor)
        if a.action == "recover":
            return {"blocked_for_reconciliation": s.recover()}
        if a.action == "requeue":
            return s.requeue(a.id, acknowledgement=a.acknowledge)
        if a.action == "cancel":
            return s.request_cancel(a.id)
        if a.action == "confirm-cancel":
            return s.confirm_cancel(a.id, a.owner, _token())
        if a.action == "run-once":
            return run_one(s, a.provider, allow_external=a.allow_external, timeout_seconds=a.timeout)
        if a.action == "mcp":
            MCPStdioServer(Gateway(s, a.workspace)).serve()
            return None
    raise FabricError("Unknown action")


def main() -> None:
    try:
        result = run()
        if result is not None:
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    except (FabricError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
