# -*- coding: utf-8 -*-
"""
tests.test_tri_tower_sync - Тесты адаптера синхронизации чекпойнтов Трёх Башен (Stage R0.4).
Покрывает:
  1. Детерминированное вычисление Merkle-корня (calculate_merkle_root);
  2. Аудит директории контрольных точек (audit_checkpoints);
  3. Формирование канонической квитанции паритета (generate_sync_receipt);
  4. Проверку инвариантов Safe Sync Gate (PRIVACY > SECURITY > DATA_INTEGRITY).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R0.4.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from rai_fabric.tri_tower_sync import (
    TriTowerSyncAdapter,
    calculate_merkle_root,
)


class TestTriTowerSync(unittest.TestCase):
    """Тесты синхронизации контрольных точек Трёх Башен."""

    def test_calculate_merkle_root_empty(self):
        empty_root = calculate_merkle_root([])
        expected = hashlib.sha256(b"EMPTY_TREE").hexdigest()
        self.assertEqual(empty_root, expected)

    def test_calculate_merkle_root_single_and_multiple(self):
        h1 = hashlib.sha256(b"block_1").hexdigest()
        h2 = hashlib.sha256(b"block_2").hexdigest()
        h3 = hashlib.sha256(b"block_3").hexdigest()

        # Одиночный хеш возвращается как есть
        self.assertEqual(calculate_merkle_root([h1]), h1)

        # Мульти-хеш детерминирован и не зависит от исходного порядка подачи
        root_forward = calculate_merkle_root([h1, h2, h3])
        root_reversed = calculate_merkle_root([h3, h2, h1])
        self.assertEqual(root_forward, root_reversed)
        self.assertEqual(len(root_forward), 64)

    def test_audit_checkpoints_missing_dir(self):
        with tempfile.TemporaryDirectory(prefix="raif_empty_repo_") as tmp:
            adapter = TriTowerSyncAdapter(repo_root=tmp)
            audit = adapter.audit_checkpoints()
            self.assertEqual(audit["checkpoints_count"], 0)
            self.assertEqual(audit["merkle_root"], hashlib.sha256(b"EMPTY_TREE").hexdigest())
            self.assertEqual(audit["items"], {})

    def test_audit_checkpoints_with_files(self):
        with tempfile.TemporaryDirectory(prefix="raif_repo_") as tmp:
            repo_path = Path(tmp)
            cp_dir = repo_path / "checkpoints"
            cp_dir.mkdir(parents=True)

            (cp_dir / "cp_01.md").write_text("# Checkpoint 1", encoding="utf-8")
            (cp_dir / "cp_02.json").write_text('{"stage": "R0.4"}', encoding="utf-8")
            (cp_dir / "ignore_me.txt").write_text("Ignore", encoding="utf-8")

            adapter = TriTowerSyncAdapter(repo_root=repo_path)
            audit = adapter.audit_checkpoints()

            self.assertEqual(audit["checkpoints_count"], 2)
            self.assertIn("cp_01.md", audit["items"])
            self.assertIn("cp_02.json", audit["items"])
            self.assertNotIn("ignore_me.txt", audit["items"])
            self.assertEqual(len(audit["merkle_root"]), 64)

    def test_generate_sync_receipt(self):
        with tempfile.TemporaryDirectory(prefix="raif_receipt_repo_") as tmp:
            adapter = TriTowerSyncAdapter(repo_root=tmp)
            custom_dest = "G:\\My Drive\\CONTROL_TOWER_BACKUP"
            receipt = adapter.generate_sync_receipt(target_dest=custom_dest)

            self.assertEqual(receipt["protocol"], "BPR5_NEXTGEN_R3.3")
            self.assertEqual(receipt["stage"], "RAIF_R0_4_TRI_TOWER_PARITY")
            self.assertIn("timestamp", receipt)
            self.assertEqual(receipt["towers"]["tower_3_gdrive"]["dest"], custom_dest)

            # Проверка инвариантов Safe Sync Gate
            gates = receipt["gate_status"]
            self.assertEqual(gates["PRIVACY"], "PASS")
            self.assertEqual(gates["SECURITY"], "PASS")
            self.assertEqual(gates["DATA_INTEGRITY"], "PASS")
            self.assertEqual(gates["KNOWLEDGE"], "PASS")
            self.assertEqual(gates["AUTO_SYNC"], "STANDBY")

    def test_seal_receipt_and_verify_parity(self):
        with tempfile.TemporaryDirectory(prefix="raif_seal_repo_") as tmp:
            repo_path = Path(tmp)
            cp_dir = repo_path / "checkpoints"
            cp_dir.mkdir(parents=True)
            (cp_dir / "cp_01.md").write_text("# Checkpoint A", encoding="utf-8")

            adapter = TriTowerSyncAdapter(repo_root=repo_path)
            out_file = adapter.seal_receipt()
            self.assertTrue(out_file.exists())
            self.assertEqual(out_file.name, "TRI_TOWER_SYNC_RECEIPT_CANONICAL.json")

            parity = adapter.verify_parity_status()
            self.assertEqual(parity["status"], "PASS")
            self.assertEqual(parity["checkpoints_count"], 1)
            self.assertTrue(parity["has_checkpoints"])


if __name__ == "__main__":
    unittest.main()

