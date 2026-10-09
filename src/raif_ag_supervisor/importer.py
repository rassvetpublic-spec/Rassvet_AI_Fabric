"""Pure validation of exported account manifests. Does not persist credentials.

Only use with explicitly user-authorized accounts and an approved local vault.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_MAX_BYTES = 1024 * 1024
_MAX_ITEMS = 200

class ImportFormatError(ValueError):
    pass

@dataclass(frozen=True)
class AccountRecord:
    email: str
    credential: str = field(repr=False)

def parse_manifest(data: bytes) -> list[AccountRecord]:
    """Parse entirely in memory; caller owns the sensitive return value."""
    if not isinstance(data, bytes) or len(data) > _MAX_BYTES:
        raise ImportFormatError("invalid input size")
    try:
        root = json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise ImportFormatError("invalid JSON encoding or syntax") from exc
    if not isinstance(root, list) or not 0 < len(root) <= _MAX_ITEMS:
        raise ImportFormatError("expected nonempty bounded array")
    accounts = []
    seen = set()
    for index, item in enumerate(root):
        if not isinstance(item, dict) or set(item) != {"email", "refresh_token"}:
            raise ImportFormatError(f"invalid record at index {index}")
        email, token = item["email"], item["refresh_token"]
        if not isinstance(email, str) or not _EMAIL.fullmatch(email):
            raise ImportFormatError(f"invalid email at index {index}")
        if not isinstance(token, str) or not token.strip() or len(token) > 8192:
            raise ImportFormatError(f"invalid credential at index {index}")
        key = email.casefold()
        if key in seen:
            raise ImportFormatError(f"duplicate account at index {index}")
        seen.add(key)
        accounts.append(AccountRecord(email, token))
    return accounts

def inspect_file(path: Path) -> int:
    """Return only count; do not print, serialize or log account content."""
    with Path(path).open("rb") as stream:
        data = stream.read(_MAX_BYTES + 1)
    return len(parse_manifest(data))
