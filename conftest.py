# -*- coding: utf-8 -*-
"""
conftest.py - Глобальная конфигурация и фикстуры pytest для CONTROL_TOWER.
Включает защиту от сбоев PermissionError на симлинках pytest-current в Windows Temp.
"""
from __future__ import annotations

__version__ = "1.0.0"

import sys

try:
    import _pytest.pathlib
    _orig_cleanup = _pytest.pathlib.cleanup_dead_symlinks

    def _safe_cleanup_dead_symlinks(root):
        try:
            _orig_cleanup(root)
        except (PermissionError, OSError):
            pass

    _pytest.pathlib.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks

    _orig_find_prefixed = getattr(_pytest.pathlib, "find_prefixed", None)
    if _orig_find_prefixed is not None:
        def _safe_find_prefixed(root, prefix):
            try:
                yield from _orig_find_prefixed(root, prefix)
            except (FileNotFoundError, PermissionError, OSError):
                return
        _pytest.pathlib.find_prefixed = _safe_find_prefixed
except Exception:
    pass
