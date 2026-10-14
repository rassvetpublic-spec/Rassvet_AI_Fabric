# -*- coding: utf-8 -*-
"""
rai_fabric.p2p_merkle - Одноранговый (Peer-to-Peer) протокол сверки и обмена Merkle-квитанциями (Stage R28 / R0.8).

Обеспечивает:
  1. Формирование компактных синхронизационных офферов (P2PMerkleOffer) для сверки паритета за O(1);
  2. Детекцию расхождений между наборами контрольных точек двух узлов флота;
  3. Генерацию криптографических Merkle Proofs для отдельных чекпойнтов без передачи всего репозитория;
  4. 100% offline детерминированную верификацию доказательств включения (inclusion proofs);
  5. Соблюдение инварианта Safe Sync Gate (Zero SSD Wear, Fail-Closed).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R28 / Rassvet_AI_Fabric.
"""

from __future__ import annotations

__version__ = "1.0.0"

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rai_fabric.fleet_common import get_repo_root
from rai_fabric.tri_tower_sync import TriTowerSyncAdapter, calculate_merkle_root

logger = logging.getLogger("raif.p2p_merkle")


def hash_pair(left: str, right: str) -> str:
    """Детерминированное вычисление SHA-256 хеша пары узлов."""
    return hashlib.sha256(f"{left}:{right}".encode("utf-8")).hexdigest()


class P2PMerkleExchange:
    """Координатор децентрализованного обмена и валидации Merkle-квитанций."""

    def __init__(self, repo_root: Optional[Path | str] = None) -> None:
        self.repo_root = Path(repo_root) if repo_root else get_repo_root()
        self.sync_adapter = TriTowerSyncAdapter(repo_root=self.repo_root)

    def create_sync_offer(self, node_id: str = "local-node") -> Dict[str, Any]:
        """Формирование P2PMerkleOffer на основе текущего состояния контрольных точек."""
        audit = self.sync_adapter.audit_checkpoints()
        return {
            "protocol": "BPR5_NEXTGEN_R3.3",
            "stage": "STAGE_R28_P2P_MERKLE",
            "node_id": node_id,
            "merkle_root": audit["merkle_root"],
            "checkpoints_count": audit["checkpoints_count"],
            "items_manifest": audit["items"],
            "timestamp": time.time(),
        }

    def compare_offers(
        self,
        local_offer: Dict[str, Any],
        remote_offer: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Сравнение локального и удалённого оффера с выявлением дельты."""
        local_root = local_offer.get("merkle_root", "")
        remote_root = remote_offer.get("merkle_root", "")

        is_parity = (local_root == remote_root) and bool(local_root)

        local_items: Dict[str, str] = local_offer.get("items_manifest", {})
        remote_items: Dict[str, str] = remote_offer.get("items_manifest", {})

        missing_in_remote: List[str] = [k for k in local_items if k not in remote_items]
        missing_in_local: List[str] = [k for k in remote_items if k not in local_items]
        divergent_files: List[str] = [
            k for k in local_items
            if k in remote_items and local_items[k] != remote_items[k]
        ]

        return {
            "is_parity": is_parity,
            "local_root": local_root,
            "remote_root": remote_root,
            "local_count": len(local_items),
            "remote_count": len(remote_items),
            "missing_in_remote": missing_in_remote,
            "missing_in_local": missing_in_local,
            "divergent_files": divergent_files,
            "needs_sync": not is_parity,
        }

    def generate_merkle_proof(
        self,
        checkpoint_name: str,
        items: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        """Генерация криптографического пути доказательства (Merkle Proof) для чекпойнта."""
        if checkpoint_name not in items:
            return None

        sorted_keys = sorted(items.keys())
        target_hash = items[checkpoint_name]

        # Строим уровни дерева с отслеживанием индекса
        current_layer = [items[k] for k in sorted_keys]
        try:
            target_idx = current_layer.index(target_hash)
        except ValueError:
            return None

        proof_path: List[Dict[str, str]] = []

        while len(current_layer) > 1:
            next_layer = []
            is_right_sibling = (target_idx % 2 == 0)
            sibling_idx = target_idx + 1 if is_right_sibling else target_idx - 1

            if sibling_idx < len(current_layer):
                sibling_hash = current_layer[sibling_idx]
                proof_path.append({
                    "direction": "right" if is_right_sibling else "left",
                    "sibling_hash": sibling_hash,
                })
            else:
                # Дублирование правого при нечетном количестве
                proof_path.append({
                    "direction": "right",
                    "sibling_hash": current_layer[target_idx],
                })

            for i in range(0, len(current_layer), 2):
                left = current_layer[i]
                right = current_layer[i + 1] if i + 1 < len(current_layer) else left
                combined = hash_pair(left, right)
                next_layer.append(combined)

            target_idx = target_idx // 2
            current_layer = next_layer

        root = current_layer[0] if current_layer else calculate_merkle_root([])

        return {
            "checkpoint_name": checkpoint_name,
            "file_hash": target_hash,
            "merkle_root": root,
            "proof_path": proof_path,
        }

    def verify_merkle_proof(
        self,
        file_hash: str,
        proof_path: List[Dict[str, str]],
        expected_root: str,
    ) -> bool:
        """Детерминированная валидация пути Merkle Proof против ожидаемого корня."""
        current = file_hash

        for step in proof_path:
            direction = step.get("direction", "right")
            sibling = step.get("sibling_hash", "")
            if direction == "right":
                current = hash_pair(current, sibling)
            else:
                current = hash_pair(sibling, current)

        return current == expected_root
