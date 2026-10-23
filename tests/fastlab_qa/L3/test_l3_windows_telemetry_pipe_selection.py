"""Deterministic Windows Named Pipe routing checks: zero real socket/pipe I/O."""
from types import SimpleNamespace
import multiprocessing.connection as ipc
import pytest
import rai_fabric.scheduler as scheduler_mod
from rai_fabric.scheduler import WorkerFleetScheduler, SchedulerConfig
from rai_fabric.store import FabricStore


@pytest.mark.parametrize("path", [r"\\.\pipe\fleet_metrics", r"\\.\pipe\custom_metrics"])
def test_windows_named_pipe_must_use_af_pipe(tmp_path, monkeypatch, path):
    calls = []
    class FakeConnection:
        def send(self, event):
            calls.append(("send", event["event_type"]))
        def close(self):
            calls.append(("close",))
    def fake_client(target, *, family):
        calls.append(("connect", target, family))
        return FakeConnection()
    monkeypatch.setattr(scheduler_mod, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(ipc, "Client", fake_client)
    with FabricStore(tmp_path / "telemetry.sqlite3", initialize=True) as store:
        scheduler = WorkerFleetScheduler(store, config=SchedulerConfig(telemetry_pipe=path))
        scheduler._emit_telemetry({"dispatched_count": 0, "total_dispatched": 0})
    assert calls == [("connect", path, "AF_PIPE"), ("send", "raif.scheduler.tick"), ("close",)]


def test_windows_pipe_unavailable_does_not_open_tcp_fallback(tmp_path, monkeypatch):
    path = r"\\.\pipe\fleet_metrics"
    attempts = []
    def failing_client(target, *, family):
        attempts.append((target, family))
        raise OSError("synthetic inaccessible named pipe")
    monkeypatch.setattr(scheduler_mod, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(ipc, "Client", failing_client)
    with FabricStore(tmp_path / "no-fallback.sqlite3", initialize=True) as store:
        scheduler = WorkerFleetScheduler(store, config=SchedulerConfig(telemetry_pipe=path))
        scheduler._emit_telemetry({"dispatched_count": 0})
    assert attempts == [(path, "AF_PIPE")]


def test_posix_telemetry_fallback_unchanged(tmp_path, monkeypatch):
    calls = []
    class FakeConnection:
        def send(self, event):
            calls.append(("send", event["event_type"]))
        def close(self):
            calls.append(("close",))
    def fake_client(target, *, family):
        calls.append(("connect", target, family))
        return FakeConnection()
    monkeypatch.setattr(scheduler_mod, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(ipc, "Client", fake_client)
    with FabricStore(tmp_path / "posix.sqlite3", initialize=True) as store:
        scheduler = WorkerFleetScheduler(store)
        scheduler._emit_telemetry({"dispatched_count": 0})
    assert calls == [("connect", ("127.0.0.1", 18899), "AF_INET"),
                     ("send", "raif.scheduler.tick"), ("close",)]
