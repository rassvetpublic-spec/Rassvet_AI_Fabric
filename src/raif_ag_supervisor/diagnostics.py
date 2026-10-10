"""Read-only diagnostic summary for Antigravity Standalone on Windows.

No token reads, keychain mutations, process termination or network access.
The report deliberately excludes usernames, emails, account IDs and paths.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .registry import LocalAccountRegistry
from .session_probe import ProcessIdentity, running_components


def default_registry_dir() -> Path:
    if os.name != "nt":
        raise OSError("Диагностика реального Standalone поддерживается на Windows")
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        raise OSError("Переменная LOCALAPPDATA не определена")
    return Path(root) / "RAiF" / "AGSupervisor"


def readonly_status(
    registry_dir: Path,
    *,
    probe: Callable[[], tuple[ProcessIdentity, ...]] | None = None,
) -> dict:
    """Return only non-secret counts and known process names/PIDs."""
    directory = Path(registry_dir)
    configured = directory.is_dir()
    if configured:
        registry = LocalAccountRegistry(directory)
        count = len(registry.ids())
        pending = registry.pending_path.exists()
    else:
        count = 0
        pending = False
    if probe is None:
        probe = running_components if os.name == "nt" else lambda: ()
    processes = probe()
    return {
        "platform": "windows" if os.name == "nt" else "unsupported",
        "registry_configured": configured,
        "registered_accounts": count,
        "recovery_required": pending,
        "processes": [{"name": p.image_name, "pid": p.pid} for p in processes],
        "session_authorization_verified": False,
        "hot_swap_verified": False,
    }
