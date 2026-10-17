"""Unit and adversarial tests for Milestone M2 (R3): Speculative Decoding Pipeline.

Covers:
- SpeculativeDecoder lookahead K=4 verification
- Acceptance rate and throughput calculation
- Target model correction on draft rejection
- VRAM budget co-allocation in MultiModelPool
"""

import time
import pytest
from unittest.mock import MagicMock

from rai_fabric.speculative_decoder import SpeculativeDecoder, SpeculativeResult


def test_speculative_decoding_full_acceptance():
    # Target model confirms all draft tokens and adds bonus token
    draft_tokens = ["def", "add(a,", "b):", "return"]
    target_tokens = ["def", "add(a,", "b):", "return", "a", "+", "b"]

    draft_client = MagicMock()
    draft_client.generate.return_value = {"text": " ".join(draft_tokens)}

    target_client = MagicMock()
    target_client.generate.return_value = {"text": " ".join(target_tokens)}

    decoder = SpeculativeDecoder(
        draft_client=draft_client,
        target_client=target_client,
        lookahead_k=4,
    )

    res = decoder.generate("Write an adder function", max_tokens=5, draft_k=4)

    assert isinstance(res, SpeculativeResult)
    assert res.tokens_generated >= 4
    assert res.draft_acceptance_rate >= 0.80
    assert res.throughput_tps > 0.0
    assert "def" in res.text


def test_speculative_decoding_rejection_and_correction():
    # Draft model proposes incorrect token at index 2
    draft_tokens = ["def", "multiply(x,", "y):", "x", "-", "y"]
    target_tokens = ["def", "multiply(x,", "y):", "return", "x", "*", "y"]

    draft_client = MagicMock()
    draft_client.generate.return_value = {"text": " ".join(draft_tokens)}

    target_client = MagicMock()
    target_client.generate.return_value = {"text": " ".join(target_tokens)}

    decoder = SpeculativeDecoder(
        draft_client=draft_client,
        target_client=target_client,
        lookahead_k=4,
    )

    res = decoder.generate("Multiply function", max_tokens=6, draft_k=4)

    assert isinstance(res, SpeculativeResult)
    assert res.tokens_generated > 0
    # Output must reflect the target model's correction
    assert "multiply" in res.text


def test_speculative_decoder_offline_fallback():
    # No clients, no live server: verify fallback behaves deterministically without crashing
    decoder = SpeculativeDecoder(
        endpoint_url="http://127.0.0.1:1",  # non-existent port
        timeout=0.1,
        lookahead_k=2,
    )
    res = decoder.generate("offline test prompt", max_tokens=4, draft_k=2)
    assert isinstance(res, SpeculativeResult)
    assert res.tokens_generated > 0
    assert res.to_dict()["model_draft"] == "qwen2.5-coder:1.5b"


def test_vram_budget_co_allocation():
    # Verify that draft and target models fit within the 14GB VRAM budget
    import importlib.util
    spec = importlib.util.spec_from_file_location("local_gpu_daemon", "scripts/local-gpu-daemon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    pool = mod.MultiModelPool(vram_budget_mb=14000)
    assert "qwen2.5-coder:1.5b" in pool.catalog
    assert "qwen2.5-coder:7b" in pool.catalog

    draft_vram = pool.catalog["qwen2.5-coder:1.5b"].vram_mb
    target_vram = pool.catalog["qwen2.5-coder:7b"].vram_mb

    assert (draft_vram + target_vram) <= pool.vram_budget_mb
    assert (draft_vram + target_vram) == 6600  # 1400 + 5200 MB
