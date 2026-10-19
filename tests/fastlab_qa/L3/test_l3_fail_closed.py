"""FASTLAB L3: source-backed negative regressions; no live model/GPU/host calls."""

import urllib.error

import pytest

from rai_fabric.scheduler import SchedulerConfig, WorkerFleetScheduler
from rai_fabric.speculative_decoder import SpeculativeDecoder
from rai_fabric.store import FabricError, FabricStore


@pytest.mark.parametrize("schema_version", ["1", "2"])
@pytest.mark.parametrize("provider", ["antigravity", "codex-app"])
def test_scheduler_real_provider_stays_queued_without_receipt(
    tmp_path, monkeypatch, schema_version, provider
):
    with FabricStore(tmp_path / "fastlab-l3.sqlite3", initialize=True) as store:
        store.db.execute(
            "UPDATE meta SET value=? WHERE key='schema_version'", (schema_version,)
        )
        task = store.submit(
            "Real-effect task must not be simulated",
            provider,
            str(tmp_path),
            task_id="l3-no-false-pass",
        )
        scheduler = WorkerFleetScheduler(store)
        worker = scheduler.register_worker("not-a-real-adapter", provider)
        monkeypatch.setattr(scheduler, "_emit_telemetry", lambda *_: None)

        summary = scheduler.tick()
        persisted = store.get(task["id"])
        assert summary["dispatched_count"] == 0
        assert summary["dispatched_tasks"] == []
        assert summary["real_pass_tasks"] == []
        assert summary["deferred_real_tasks"] == [task["id"]]
        assert summary["real_provider_gate"] == "NO_VERIFIED_TARGET_ADAPTER_OR_RECEIPT"
        assert summary["mock_done_tasks"] == []
        assert persisted["status"] == "QUEUED"
        assert persisted["attempt"] == 0
        assert persisted["external_run_id"] is None
        assert worker.tasks_completed == 0
        assert worker.tasks_failed == 0
        assert scheduler._account_index == 0
        assert not any(
            event["type"] in ("CLAIMED", "FINISHED")
            for event in store.events(task["id"])
        )

        # No direct store.claim() bypass in legacy schema-v1 or W2 schema-v2.
        with pytest.raises(FabricError):
            store.claim("not-an-adapter", provider=provider, task_id=task["id"])
        assert store.claim("generic-poller", task_id=task["id"]) is None
        assert store.get(task["id"])["status"] == "QUEUED"


def test_mock_completion_explicitly_not_real_qa(tmp_path, monkeypatch):
    with FabricStore(tmp_path / "mock.sqlite3", initialize=True) as store:
        task = store.submit("A simulation only", "mock", str(tmp_path))
        scheduler = WorkerFleetScheduler(store)
        scheduler.register_worker("Mock", "mock")
        monkeypatch.setattr(scheduler, "_emit_telemetry", lambda *_: None)
        summary = scheduler.tick()
        assert summary["mock_done_tasks"] == [task["id"]]
        assert summary["real_pass_tasks"] == []
        assert summary["deferred_real_tasks"] == []
        assert store.get(task["id"])["status"] == "COMPLETE"
        assert store.latest_checkpoint(task["id"])["evidence"]["simulation"] is True


def test_deferred_real_task_does_not_starve_mock_fifo(tmp_path, monkeypatch):
    with FabricStore(tmp_path / "queue.sqlite3", initialize=True) as store:
        real = store.submit(
            "Not authorized", "antigravity", str(tmp_path), task_id="real-first"
        )
        mock = store.submit("Safe synthetic", "mock", str(tmp_path), task_id="mock-second")
        store.db.execute("UPDATE tasks SET created_at=1 WHERE id=?", (real["id"],))
        store.db.execute("UPDATE tasks SET created_at=2 WHERE id=?", (mock["id"],))
        scheduler = WorkerFleetScheduler(
            store, config=SchedulerConfig(max_concurrent_workers=1)
        )
        scheduler.register_worker("Real (unavailable)", "antigravity")
        scheduler.register_worker("Mock", "mock")
        monkeypatch.setattr(scheduler, "_emit_telemetry", lambda *_: None)
        summary = scheduler.tick()
        assert summary["mock_done_tasks"] == [mock["id"]]
        assert summary["real_pass_tasks"] == []
        assert summary["deferred_real_tasks"] == [real["id"]]
        assert store.get(real["id"])["status"] == "QUEUED"
        assert store.get(real["id"])["attempt"] == 0
        assert store.get(mock["id"])["status"] == "COMPLETE"


def test_decoder_rejects_nonempty_but_wrong_draft_without_prompt_leak():
    target_prompts = []

    def target(_model, prompt, _limit):
        target_prompts.append(prompt)
        return "correct"

    decoder = SpeculativeDecoder(
        draft_client=lambda *_: "wrong",
        target_client=target,
        lookahead_k=1,
    )
    result = decoder.generate("seed", max_tokens=1, draft_k=1)
    assert target_prompts == ["seed"]
    assert result.text == "correct"
    assert result.tokens_accepted == 0
    assert result.tokens_generated == 1


def test_decoder_stops_at_first_mismatch_and_preserves_target_prefix():
    decoder = SpeculativeDecoder(
        draft_client=lambda *_: "alpha wrong omega",
        target_client=lambda *_: "alpha right delta",
        lookahead_k=3,
    )
    result = decoder.generate("seed", max_tokens=2, draft_k=3)
    assert result.text == "alpha right"
    assert result.tokens_accepted == 1
    assert result.tokens_generated == 2


def test_decoder_bonus_is_not_draft_acceptance():
    decoder = SpeculativeDecoder(
        draft_client=lambda *_: "a b",
        target_client=lambda *_: "a b c",
        lookahead_k=2,
    )
    result = decoder.generate("seed", max_tokens=3, draft_k=2)
    assert result.text == "a b c"
    assert result.tokens_accepted == 2
    assert result.draft_acceptance_rate == 1.0
    assert result.tokens_generated == 3


def test_decoder_unavailable_http_fails_closed(monkeypatch):
    def refuse_http(*_args, **_kwargs):
        raise urllib.error.URLError("offline test")

    monkeypatch.setattr(
        "rai_fabric.speculative_decoder.urllib.request.urlopen", refuse_http
    )
    decoder = SpeculativeDecoder(
        endpoint_url="http://127.0.0.1:1", timeout=0.01
    )
    with pytest.raises(RuntimeError, match="model query failed"):
        decoder.generate("no fabricated source", max_tokens=2)


def test_store_cannot_mark_real_pass_even_with_injected_lease(tmp_path):
    import hashlib
    import time
    for schema_version in ("1", "2"):
        with FabricStore(tmp_path / f"lease-{schema_version}.sqlite3", initialize=True) as store:
            store.db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (schema_version,))
            task = store.submit("Not a real effect", "antigravity", str(tmp_path))
            store.db.execute(
                "UPDATE tasks SET status='RUNNING', lease_owner=?, lease_hash=?, "
                "lease_epoch=1, lease_deadline=? WHERE id=?",
                ("synthetic-owner", hashlib.sha256(b"fake-lease").hexdigest(),
                 time.time() + 120, task["id"]),
            )
            with pytest.raises(FabricError, match="PASS"):
                store.finish(task["id"], "synthetic-owner", "fake-lease", verdict="PASS",
                             response="no real receipt", evidence={"simulation": True})
            assert store.get(task["id"])["status"] == "RUNNING"
            assert store.result(task["id"]) is None


def test_callable_model_client_none_is_not_fake_text():
    decoder = SpeculativeDecoder(draft_client=lambda *_: None, target_client=lambda *_: "ok")
    with pytest.raises((TypeError, ValueError, RuntimeError), match="model client"):
        decoder.generate("guard", max_tokens=1)


def test_generate_client_missing_response_is_rejected():
    class MissingResponse:
        def generate(self, _request):
            return {"response": None}
    decoder = SpeculativeDecoder(draft_client=MissingResponse(), target_client=lambda *_: "ok")
    with pytest.raises((TypeError, ValueError, RuntimeError), match="model client"):
        decoder.generate("guard", max_tokens=1)


def test_replication_model_name_cannot_escape_windows_model_root(tmp_path):
    from pathlib import PureWindowsPath
    from rai_fabric.model_replicator import ModelReplicator
    root = tmp_path / "models"
    replicator = ModelReplicator(models_dir=root)
    for name in (r"..\..\outside", r"C:\temp\outside", r"\\server\share\unexpected"):
        for resulting_path in (replicator._get_model_path(name), replicator._get_staging_chunk_path(name, 0)):
            win_path = PureWindowsPath(str(resulting_path))
            assert ".." not in win_path.parts
            assert not win_path.is_absolute() or str(win_path).startswith(str(PureWindowsPath(str(root))))


def test_direct_chunk_import_rejects_out_of_manifest_bounds(tmp_path):
    import hashlib
    from rai_fabric.model_replicator import ModelReplicator
    replicator = ModelReplicator(models_dir=tmp_path / "models")
    payload = b"TEST"
    digest = hashlib.sha256(payload).hexdigest()
    assert replicator.import_chunk_direct("safe_model", 0, 128, payload, digest, total_size=4) is False
    assert not replicator._get_model_path("safe_model").exists()
    assert replicator.import_chunk_direct("safe_model", -1, 0, payload, digest, total_size=4) is False
    assert not replicator._get_model_path("safe_model").exists()


def test_peer_replication_corrupt_existing_model_is_not_verified(tmp_path):
    import hashlib
    from rai_fabric.model_replicator import ModelReplicator, ModelManifest
    r = ModelReplicator(models_dir=tmp_path / "models")
    good, bad = b"correct1", b"bad-data"
    digest = hashlib.sha256(good).hexdigest()
    manifest = ModelManifest("safe-model", len(good), len(good), 1, [digest], digest)
    r._get_model_path("safe-model").write_bytes(bad)
    status = r.get_model_status("safe-model", manifest)
    assert status["status"] == "CORRUPTED"
    result = r.replicate_from_peer(manifest, lambda *_: good)
    assert result["status"] == "SUCCESS"
    assert r._get_model_path("safe-model").read_bytes() == good
    assert r.get_model_status("safe-model", manifest)["status"] == "COMPLETED"


def test_model_file_presence_without_manifest_is_not_attestation(tmp_path):
    from rai_fabric.model_replicator import ModelReplicator
    r = ModelReplicator(models_dir=tmp_path / "models")
    r._get_model_path("unverified").write_bytes(b"arbitrary")
    assert r.get_model_status("unverified")["status"] == "PRESENT_UNVERIFIED"


def test_replicator_refuses_finalized_wrong_total_size(tmp_path):
    import hashlib
    from rai_fabric.model_replicator import ModelReplicator, ModelManifest
    r = ModelReplicator(models_dir=tmp_path / "models")
    chunk = b"abcd"
    digest = hashlib.sha256(chunk).hexdigest()
    manifest = ModelManifest("toy", 1, len(chunk), 1, [digest], digest)
    assert r.import_chunk("toy", 0, chunk, manifest)
    result, _ = r.finalize_model("toy", manifest)
    assert result is False
    assert not r._get_model_path("toy").is_file()


def test_replicator_cached_verification_invalidated_on_file_change(tmp_path):
    import hashlib
    import os
    from rai_fabric.model_replicator import ModelReplicator, ModelManifest
    r = ModelReplicator(models_dir=tmp_path / "models")
    good = b"VALID001"
    digest = hashlib.sha256(good).hexdigest()
    manifest = ModelManifest("cached", len(good), len(good), 1, [digest], digest)
    assert r.import_chunk("cached", 0, good, manifest)
    ok, _ = r.finalize_model("cached", manifest)
    assert ok is True
    assert r.get_model_status("cached", manifest)["status"] == "COMPLETED"
    model_path = r._get_model_path("cached")
    original_mtime = model_path.stat().st_mtime_ns
    model_path.write_bytes(b"INVALID1")
    os.utime(model_path, ns=(original_mtime + 10_000_000_000, original_mtime + 10_000_000_000))
    assert r.get_model_status("cached", manifest)["status"] == "CORRUPTED"


def test_model_manifest_chunk_hashes_must_match_root_on_finalize(tmp_path):
    import hashlib
    from rai_fabric.model_replicator import ModelReplicator, ModelManifest
    r = ModelReplicator(models_dir=tmp_path / "models")
    good = b"ACTUAL"
    actual_hash = hashlib.sha256(good).hexdigest()
    wrong_hash = hashlib.sha256(b"NOT-MATCHING").hexdigest()
    manifest = ModelManifest("inconsistent", len(good), len(good), 1, [wrong_hash], actual_hash)
    r._get_staging_chunk_path("inconsistent", 0).write_bytes(good)
    ok, _ = r.finalize_model("inconsistent", manifest)
    assert ok is False
    assert not r._get_model_path("inconsistent").is_file()
