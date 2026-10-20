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
import hmac
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
        # Offers are untrusted hints. Matching self-declared roots alone are
        # insufficient: names can differ while the hash multiset is identical.
        local_offer = local_offer if isinstance(local_offer, dict) else {}
        remote_offer = remote_offer if isinstance(remote_offer, dict) else {}
        local_root = local_offer.get("merkle_root", "")
        remote_root = remote_offer.get("merkle_root", "")
        local_raw = local_offer.get("items_manifest")
        remote_raw = remote_offer.get("items_manifest")
        local_items: Dict[str, str] = local_raw if isinstance(local_raw, dict) else {}
        remote_items: Dict[str, str] = remote_raw if isinstance(remote_raw, dict) else {}
        items_valid = (isinstance(local_raw, dict) and isinstance(remote_raw, dict) and
                       all(isinstance(k, str) and isinstance(v, str) and len(v) == 64 and
                           all(c in "0123456789abcdef" for c in v)
                           for itemset in (local_items, remote_items)
                           for k, v in itemset.items()))
        local_calculated = (calculate_merkle_root(list(local_items.values()))
                            if items_valid else None)
        remote_calculated = (calculate_merkle_root(list(remote_items.values()))
                             if items_valid else None)
        is_parity = bool(items_valid and isinstance(local_root, str) and local_root and
                         local_items == remote_items and local_root == remote_root and
                         local_root == local_calculated and remote_root == remote_calculated)

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
        if (not isinstance(items, dict) or checkpoint_name not in items or
                not all(isinstance(name, str) and isinstance(digest, str) and
                        len(digest) == 64 and
                        all(ch in "0123456789abcdef" for ch in digest)
                        for name, digest in items.items())):
            return None

        # Canonical TriTower root sorts by digest VALUE, not filename.
        # Stable filename tie-break selects the intended leaf when hashes repeat.
        ordered = sorted(items.items(), key=lambda pair: (pair[1], pair[0]))
        target_hash = items[checkpoint_name]
        current_layer = [digest for _, digest in ordered]
        target_idx = next(i for i, (name, _) in enumerate(ordered)
                          if name == checkpoint_name)

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
        is_hash = lambda h: (isinstance(h, str) and len(h) == 64 and
                             all(c in "0123456789abcdef" for c in h))
        if (not is_hash(file_hash) or not is_hash(expected_root) or
                not isinstance(proof_path, list) or len(proof_path) > 64):
            return False
        current = file_hash
        for step in proof_path:
            if (not isinstance(step, dict) or
                    step.get("direction") not in ("left", "right") or
                    not is_hash(step.get("sibling_hash"))):
                return False
            sibling = step["sibling_hash"]
            if step["direction"] == "right":
                current = hash_pair(current, sibling)
            else:
                current = hash_pair(sibling, current)
        return hmac.compare_digest(current, expected_root)
