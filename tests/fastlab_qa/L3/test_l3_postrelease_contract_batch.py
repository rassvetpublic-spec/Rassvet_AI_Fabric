"""L3 post-release release-safe scheduler contract regressions; disposable SQLite only."""
from __future__ import annotations

import pytest
import rai_fabric.scheduler as scheduler_mod
import rai_fabric.worker as worker_mod
from rai_fabric.scheduler import SchedulerConfig, WorkerFleetScheduler
from rai_fabric.store import FabricError, FabricStore


def test_selected_mock_cannot_dispatch_another_task_when_canceled(tmp_path, monkeypatch):
    """Race after the scheduler's SELECT must not claim an unselected mock."""
    with FabricStore(tmp_path / 'race.sqlite3', initialize=True) as store:
        a = store.submit('selected', 'mock', str(tmp_path), task_id='race-a')
        b = store.submit('not selected', 'mock', str(tmp_path), task_id='race-b')
        with store.atomic():
            store.db.execute('UPDATE tasks SET created_at=1 WHERE id=?', (a['id'],))
            store.db.execute('UPDATE tasks SET created_at=2 WHERE id=?', (b['id'],))
        scheduler = WorkerFleetScheduler(store, config=SchedulerConfig(max_concurrent_workers=1))
        scheduler.register_worker('Mock', 'mock')
        monkeypatch.setattr(scheduler, '_emit_telemetry', lambda *_: None)
        original_run_one = scheduler_mod.run_one
        def cancel_selected_before_claim(*args, **kwargs):
            store.request_cancel(a['id'])
            return original_run_one(*args, **kwargs)
        monkeypatch.setattr(scheduler_mod, 'run_one', cancel_selected_before_claim)
        report = scheduler.tick()
        assert report['dispatched_tasks'] == []
        assert store.get(a['id'])['status'] == 'CANCELLED'
        assert store.get(b['id'])['status'] == 'QUEUED'
        assert store.get(b['id'])['attempt'] == 0


@pytest.mark.parametrize('provider', ['antigravity','codex-app'])
@pytest.mark.parametrize('schema_version', ['1', '2'])
def test_real_provider_refused_without_executable_probe(tmp_path, monkeypatch, provider, schema_version):
    """Legacy --allow-external flag alone cannot satisfy missing receipt/adapter."""
    with FabricStore(tmp_path / f'{provider}.sqlite3', initialize=True) as store:
        store.db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (schema_version,))
        task = store.submit('No live execution', provider, str(tmp_path), task_id='blocked-real')
        def forbidden(*args, **kwargs):
            raise AssertionError('executor probe or subprocess was attempted')
        monkeypatch.setattr(worker_mod.shutil, 'which', forbidden)
        monkeypatch.setattr(worker_mod.subprocess, 'Popen', forbidden)
        with pytest.raises(FabricError, match=r'verified (target|effect)'):
            worker_mod.run_one(store, provider, allow_external=True)
        assert store.get(task['id'])['status'] == 'QUEUED'
        assert store.get(task['id'])['attempt'] == 0
        assert not any(e['type'] == 'CLAIMED' for e in store.events(task['id']))


@pytest.mark.parametrize('count,overflow', [(50, False),(51, True),(53, True)])
def test_deferred_real_list_advertises_truncation(tmp_path, monkeypatch, count, overflow):
    with FabricStore(tmp_path / 'backlog.sqlite3', initialize=True) as store:
        for i in range(count):
            store.submit(f'Defer {i}', 'antigravity', str(tmp_path), task_id=f'real-{i:03}')
        scheduler = WorkerFleetScheduler(store)
        monkeypatch.setattr(scheduler, '_emit_telemetry', lambda *_: None)
        report = scheduler.tick()
        assert len(report['deferred_real_tasks']) == 50
        assert report['deferred_real_has_more'] is overflow
        assert report['real_pass_tasks'] == []
        assert report['dispatched_count'] == 0
        assert store.db.execute("SELECT COUNT(*) FROM tasks WHERE attempt!=0").fetchone()[0] == 0


def test_mock_legacy_direct_run_one_still_works(tmp_path):
    """New exact-task optional parameter must preserve older direct callers."""
    with FabricStore(tmp_path / 'legacy.sqlite3', initialize=True) as store:
        task = store.submit('Mock via direct invocation', 'mock', str(tmp_path), task_id='legacy-mock')
        result = worker_mod.run_one(store, 'mock')
        assert result['status'] == 'COMPLETE'
        assert result['id'] == task['id']


def test_direct_mock_task_id_is_exact_when_others_ready(tmp_path):
    with FabricStore(tmp_path / 'pin-direct.sqlite3', initialize=True) as store:
        a = store.submit('first', 'mock', str(tmp_path), task_id='pin-first')
        b = store.submit('second', 'mock', str(tmp_path), task_id='pin-second')
        outcome = worker_mod.run_one(store, 'mock', task_id=b['id'])
        assert outcome['status'] == 'COMPLETE'
        assert outcome['id'] == b['id']
        assert store.get(a['id'])['status'] == 'QUEUED'
        assert store.get(a['id'])['attempt'] == 0


def test_mock_cannot_claim_real_task_by_explicit_id(tmp_path):
    with FabricStore(tmp_path / 'pin-deny.sqlite3', initialize=True) as store:
        real = store.submit('real', 'antigravity', str(tmp_path), task_id='pin-real')
        mock = store.submit('mock', 'mock', str(tmp_path), task_id='pin-mock')
        outcome = worker_mod.run_one(store, 'mock', task_id=real['id'])
        assert outcome['status'] == 'NO_READY_TASK'
        assert store.get(real['id'])['status'] == 'QUEUED'
        assert store.get(mock['id'])['status'] == 'QUEUED'
        assert store.get(mock['id'])['attempt'] == 0
