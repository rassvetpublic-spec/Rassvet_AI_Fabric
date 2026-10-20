"""L3 Wave2 regression: selected mock work must be both runnable and serviced.

All tests use temporary SQLite and synthetic workers; no external executors.
"""
from __future__ import annotations

from rai_fabric.scheduler import SchedulerConfig, WorkerFleetScheduler
from rai_fabric.store import FabricStore


def _timestamps(store: FabricStore, ordered_ids: list[str]) -> None:
    with store.atomic():
        for ix, task_id in enumerate(ordered_ids, 1):
            store.db.execute("UPDATE tasks SET created_at=? WHERE id=?", (float(ix), task_id))


def test_unserved_mock_provider_does_not_starve_registered_mock(tmp_path, monkeypatch):
    """A queued codex-mock with NO registered worker must not consume the only slot."""
    with FabricStore(tmp_path / "fairness-unserved.sqlite3", initialize=True) as store:
        no_worker = store.submit("No codex-mock worker", "codex-mock", str(tmp_path),
                                 task_id="codex-unserved")
        runnable = store.submit("Ready mock with a worker", "mock", str(tmp_path),
                                task_id="mock-served")
        _timestamps(store, [no_worker["id"], runnable["id"]])
        scheduler = WorkerFleetScheduler(store, config=SchedulerConfig(max_concurrent_workers=1))
        scheduler.register_worker("Only mock worker", "mock")
        monkeypatch.setattr(scheduler, "_emit_telemetry", lambda *_: None)
        result = scheduler.tick()
        assert result["mock_done_tasks"] == [runnable["id"]]
        assert result["dispatched_count"] == 1
        assert store.get(runnable["id"])["status"] == "COMPLETE"
        assert store.get(no_worker["id"])["status"] == "QUEUED"
        assert store.get(no_worker["id"])["attempt"] == 0


def test_dependency_blocked_mock_provider_does_not_starve_ready_other_provider(tmp_path, monkeypatch):
    """A codex-mock blocked on a QUEUED real dependency must not mask a ready mock."""
    with FabricStore(tmp_path / "fairness-dependency.sqlite3", initialize=True) as store:
        real_parent = store.submit("Never dispatch real", "antigravity", str(tmp_path),
                                   task_id="real-parent")
        blocked = store.submit("Pending real dependency", "codex-mock", str(tmp_path),
                               task_id="codex-dependent", depends_on=[real_parent["id"]])
        ready = store.submit("Runnable mock", "mock", str(tmp_path),
                             task_id="mock-unrelated")
        _timestamps(store, [real_parent["id"], blocked["id"], ready["id"]])
        scheduler = WorkerFleetScheduler(store, config=SchedulerConfig(max_concurrent_workers=1))
        scheduler.register_worker("Blocked provider worker", "codex-mock")
        scheduler.register_worker("Runnable provider worker", "mock")
        monkeypatch.setattr(scheduler, "_emit_telemetry", lambda *_: None)
        result = scheduler.tick()
        assert result["mock_done_tasks"] == [ready["id"]]
        assert result["real_pass_tasks"] == []
        assert store.get(real_parent["id"])["status"] == "QUEUED"
        assert store.get(real_parent["id"])["attempt"] == 0
        assert store.get(blocked["id"])["status"] == "QUEUED"
        assert store.get(ready["id"])["status"] == "COMPLETE"
