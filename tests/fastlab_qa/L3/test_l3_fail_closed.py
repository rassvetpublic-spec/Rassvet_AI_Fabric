"""FASTLAB L3: source-backed negative regressions; no live model/GPU/host calls."""

import urllib.error

import pytest

from rai_fabric.scheduler import WorkerFleetScheduler
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
        assert store.get(task["id"])["status"] == "COMPLETE"
        assert store.latest_checkpoint(task["id"])["evidence"]["simulation"] is True


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
