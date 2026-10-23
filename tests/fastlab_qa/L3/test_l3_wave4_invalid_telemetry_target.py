"""L3 Wave4 — an invalid Windows metrics target must not trigger TCP fallback.

No actual network or named-pipe access: multiprocessing.Client is monkeypatched.
"""
from __future__ import annotations

import multiprocessing.connection as ipc
from types import SimpleNamespace

import pytest

import rai_fabric.scheduler as scheduler_mod
from rai_fabric.scheduler import SchedulerConfig, WorkerFleetScheduler
from rai_fabric.store import FabricStore


@pytest.mark.parametrize("invalid_target", [
    "",
    "telemetry",  # Not a Windows Named Pipe
    "127.0.0.1:18899",  # Never interpret a malformed pipe as implicit TCP
    r"\\remote-host\pipe\fleet_metrics",  # The local AF_PIPE path is not this
    "\\\\.\\pipe\\",  # Pipe root, but no pipe name
])
def test_windows_invalid_pipe_config_must_fail_closed_before_any_client(
    tmp_path, monkeypatch, invalid_target
):
    attempts = []

    def spy_client(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("unexpected socket/pipe attempt")

    monkeypatch.setattr(scheduler_mod, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(ipc, "Client", spy_client)

    with FabricStore(tmp_path / "isolated-wave4.sqlite3", initialize=True) as store:
        scheduler = WorkerFleetScheduler(store, config=SchedulerConfig(telemetry_pipe=invalid_target))
        scheduler._emit_telemetry({"dispatched_count": 0})
    assert attempts == []
