# -*- coding: utf-8 -*-
"""
tests/test_p2p_merkle.py - 100% offline-safe тесты протокола P2P Merkle Exchange (Stage R28).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from rai_fabric.p2p_merkle import P2PMerkleExchange, hash_pair
from rai_fabric.tri_tower_sync import calculate_merkle_root


class TestP2PMerkleExchange:
    def test_hash_pair_deterministic(self) -> None:
        h1 = hash_pair("hashA", "hashB")
        h2 = hash_pair("hashA", "hashB")
        assert h1 == h2
        assert len(h1) == 64
        # Order matters
        assert hash_pair("hashA", "hashB") != hash_pair("hashB", "hashA")

    def test_create_sync_offer_and_compare_identical(self, tmp_path: Path) -> None:
        cp_dir = tmp_path / "checkpoints"
        cp_dir.mkdir()
        (cp_dir / "001_genesis.json").write_text("{\"v\": 1}", encoding="utf-8")
        (cp_dir / "002_data.json").write_text("{\"v\": 2}", encoding="utf-8")

        exchange = P2PMerkleExchange(repo_root=tmp_path)
        offer1 = exchange.create_sync_offer(node_id="node-01")
        offer2 = exchange.create_sync_offer(node_id="node-02")

        diff = exchange.compare_offers(offer1, offer2)
        assert diff["is_parity"] is True
        assert diff["needs_sync"] is False
        assert diff["missing_in_remote"] == []
        assert diff["missing_in_local"] == []
        assert diff["divergent_files"] == []

    def test_compare_offers_with_divergence(self) -> None:
        exchange = P2PMerkleExchange()
        offer_a = {
            "merkle_root": "rootA",
            "items_manifest": {
                "file1.json": "hash1",
                "file2.json": "hash2_v1",
            },
        }
        offer_b = {
            "merkle_root": "rootB",
            "items_manifest": {
                "file2.json": "hash2_v2",
                "file3.json": "hash3",
            },
        }

        diff = exchange.compare_offers(offer_a, offer_b)
        assert diff["is_parity"] is False
        assert diff["needs_sync"] is True
        assert "file1.json" in diff["missing_in_remote"]
        assert "file3.json" in diff["missing_in_local"]
        assert "file2.json" in diff["divergent_files"]

    def test_generate_and_verify_merkle_proof(self) -> None:
        exchange = P2PMerkleExchange()
        items = {
            "001.json": "1" * 64,
            "002.json": "2" * 64,
            "003.json": "3" * 64,
            "004.json": "4" * 64,
        }

        proof = exchange.generate_merkle_proof("002.json", items)
        assert proof is not None
        assert proof["checkpoint_name"] == "002.json"
        assert proof["file_hash"] == "2" * 64

        # Успешная валидация
        assert exchange.verify_merkle_proof(
            file_hash=proof["file_hash"],
            proof_path=proof["proof_path"],
            expected_root=proof["merkle_root"],
        )

        # Фальсификация хеша приводит к FAIL (Fail-Closed)
        assert not exchange.verify_merkle_proof(
            file_hash="9" * 64,
            proof_path=proof["proof_path"],
            expected_root=proof["merkle_root"],
        )
