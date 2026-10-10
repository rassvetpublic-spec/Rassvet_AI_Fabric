"""Advisory exclusive file locking for registry mutation.

Locks are released by the OS when the owning process terminates. Never put
credentials or account identifiers into this lock file.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class RegistryBusyError(RuntimeError):
    pass


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Fail closed if another process already owns the registry write lock."""
    with Path(path).open("a+b") as handle:
        locked = False
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise RegistryBusyError("registry is already locked by another process") from None
        try:
            yield
        finally:
            if locked:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
