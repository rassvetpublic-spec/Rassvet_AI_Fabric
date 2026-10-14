# -*- coding: utf-8 -*-
"""
tests/test_parity_cron.py - 100% offline-safe тесты для планировщика паритета Трёх Башен (Stage R26 / R0.4).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from rai_fabric.parity_cron import TriTowerParityCron, main
from rai_fabric.tri_tower_sync import TriTowerSyncAdapter


class TestTriTowerParityCron:
    @pytest.fixture
    def mock_repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        cp_dir = repo / "checkpoints"
        cp_dir.mkdir()
        (cp_dir / "001_genesis.json").write_text(json.dumps({"stage": "R0"}), encoding="utf-8")
        (cp_dir / "002_checkpoint.md").write_text("# Checkpoint 2\nContent", encoding="utf-8")
        return repo

    def test_audit_initial_run_seals_receipt(self, mock_repo: Path) -> None:
        adapter = TriTowerSyncAdapter(repo_root=mock_repo)
        cron = TriTowerParityCron(repo_root=mock_repo, sync_adapter=adapter)

        res = cron.run_audit()

        assert res["status"] == "PASS"
        assert res["audit_index"] == 1
        assert res["checkpoints_count"] == 2
        assert len(res["merkle_root"]) == 64
        assert res["changed"] is False
        assert res["needs_seal"] is True

        receipt_path = mock_repo / "checkpoints" / "TRI_TOWER_SYNC_RECEIPT_CANONICAL.json"
        assert receipt_path.exists()
        receipt_data = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt_data["merkle_root"] == res["merkle_root"]

    def test_audit_unchanged_checkpoints_no_reseal(self, mock_repo: Path) -> None:
        adapter = TriTowerSyncAdapter(repo_root=mock_repo)
        cron = TriTowerParityCron(repo_root=mock_repo, sync_adapter=adapter)

        # 1st run
        cron.run_audit()

        # 2nd run without changing files
        res2 = cron.run_audit()
        assert res2["status"] == "PASS"
        assert res2["audit_index"] == 2
        assert res2["changed"] is False
        assert res2["needs_seal"] is False

    def test_audit_detected_checkpoint_change(self, mock_repo: Path) -> None:
        adapter = TriTowerSyncAdapter(repo_root=mock_repo)
        cron = TriTowerParityCron(repo_root=mock_repo, sync_adapter=adapter)

        res1 = cron.run_audit()
        root1 = res1["merkle_root"]

        # Modify a checkpoint
        (mock_repo / "checkpoints" / "003_new.json").write_text(json.dumps({"stage": "R26"}), encoding="utf-8")

        res2 = cron.run_audit()
        root2 = res2["merkle_root"]

        assert root1 != root2
        assert res2["changed"] is True
        assert res2["needs_seal"] is True
        assert res2["checkpoints_count"] == 3

    def test_cli_main_once_json(self, mock_repo: Path) -> None:
        with patch("rai_fabric.parity_cron.get_repo_root", return_value=mock_repo):
            output = io.StringIO()
            with patch("sys.stdout", output):
                code = main(["--once", "--json"])
            assert code == 0
            parsed = json.loads(output.getvalue())
            assert parsed["status"] == "PASS"
            assert parsed["checkpoints_count"] == 2

    def test_run_forever_max_iterations(self, mock_repo: Path) -> None:
        adapter = TriTowerSyncAdapter(repo_root=mock_repo)
        cron = TriTowerParityCron(repo_root=mock_repo, sync_adapter=adapter)

        with patch("time.sleep", return_value=None):
            cron.run_forever(interval_seconds=1, max_iterations=2)

        assert cron.audit_count == 2
