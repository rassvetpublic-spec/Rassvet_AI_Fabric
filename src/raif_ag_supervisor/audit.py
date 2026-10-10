"""CP-54C1/54D strict redact-by-construction stage audit.

No raw exception, paths, identity strings, command lines or callback outputs
are accepted; serialization contains fixed-schema reason codes only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_STATES = frozenset(("START", "PASS", "BLOCKED", "SAFE_FAIL", "SKIPPED"))


@dataclass
class StageAudit:
    """In-memory event journal; caller owns controlled output directory."""
    events: list[dict] = field(default_factory=list)

    def append(self, stage: str, state: str, code: str) -> None:
        if not isinstance(stage, str) or not _CODE.fullmatch(stage):
            raise ValueError("AUDIT_STAGE_INVALID")
        if state not in _STATES:
            raise ValueError("AUDIT_STATE_INVALID")
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise ValueError("AUDIT_CODE_INVALID")
        if len(self.events) >= 256:
            raise ValueError("AUDIT_EVENT_LIMIT")
        self.events.append({"sequence": len(self.events) + 1, "stage": stage,
                            "state": state, "safe_error_code": code})

    def jsonl(self) -> str:
        return "".join(json.dumps(x, separators=(",", ":"), sort_keys=True) + "\n"
                       for x in self.events)

    def receipt(self) -> dict:
        return {"schema": "RAIF_BIGWAVE_AUDIT/1", "events": len(self.events),
                "blocked": sum(x["state"] in ("BLOCKED", "SAFE_FAIL") for x in self.events),
                "raw_exception_exported": False, "secrets_exported": False,
                "identity_verified": False}
