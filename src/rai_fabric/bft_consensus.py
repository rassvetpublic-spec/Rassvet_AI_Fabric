"""rai_fabric.bft_consensus - Византийский консенсус квитанций Трёх Башен (Stage R32).

Реализует отказоустойчивый византийский кворум (PBFT-like) для согласования
канонического Merkle Root квитанций между узлами флота (N >= 3f + 1, кворум 2f + 1).
"""

from __future__ import annotations

__version__ = "1.0.0"

import hashlib
import hmac
import json
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class BFTPhase(str, Enum):
    IDLE = "IDLE"
    PRE_PREPARED = "PRE_PREPARED"
    PREPARED = "PREPARED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"


class ReceiptProposal:
    """Предложение квитанции паритета для консенсуса."""

    def __init__(
        self,
        sequence_number: int,
        epoch: int,
        merkle_root: str,
        checkpoints_count: int,
        timestamp: float,
        proposer_id: str,
        signature: str = "",
    ) -> None:
        self.sequence_number = sequence_number
        self.epoch = epoch
        self.merkle_root = merkle_root
        self.checkpoints_count = checkpoints_count
        self.timestamp = timestamp
        self.proposer_id = proposer_id
        self.signature = signature

    def compute_digest(self) -> bytes:
        raw = f"{self.sequence_number}:{self.epoch}:{self.merkle_root}:{self.checkpoints_count}:{self.timestamp:.3f}:{self.proposer_id}"
        return hashlib.sha256(raw.encode("utf-8")).digest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence_number": self.sequence_number,
            "epoch": self.epoch,
            "merkle_root": self.merkle_root,
            "checkpoints_count": self.checkpoints_count,
            "timestamp": self.timestamp,
            "proposer_id": self.proposer_id,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ReceiptProposal:
        return cls(
            sequence_number=d["sequence_number"],
            epoch=d["epoch"],
            merkle_root=d["merkle_root"],
            checkpoints_count=d["checkpoints_count"],
            timestamp=d["timestamp"],
            proposer_id=d["proposer_id"],
            signature=d.get("signature", ""),
        )


class BFTVote:
    """Голос валидатора в фазах PREPARE или COMMIT."""

    def __init__(
        self,
        phase: str,
        sequence_number: int,
        epoch: int,
        merkle_root: str,
        voter_id: str,
        signature: str = "",
    ) -> None:
        self.phase = phase
        self.sequence_number = sequence_number
        self.epoch = epoch
        self.merkle_root = merkle_root
        self.voter_id = voter_id
        self.signature = signature

    def compute_digest(self) -> bytes:
        raw = f"{self.phase}:{self.sequence_number}:{self.epoch}:{self.merkle_root}:{self.voter_id}"
        return hashlib.sha256(raw.encode("utf-8")).digest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "sequence_number": self.sequence_number,
            "epoch": self.epoch,
            "merkle_root": self.merkle_root,
            "voter_id": self.voter_id,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BFTVote:
        return cls(
            phase=d["phase"],
            sequence_number=d["sequence_number"],
            epoch=d["epoch"],
            merkle_root=d["merkle_root"],
            voter_id=d["voter_id"],
            signature=d.get("signature", ""),
        )


class BFTConsensusNode:
    """Узел валидатора византийского консенсуса квитанций."""

    def __init__(
        self,
        node_id: str,
        cluster_nodes: List[str],
        secret_key: str = "raif_bft_cluster_secret_key",
    ) -> None:
        self.node_id = node_id
        self.cluster_nodes = sorted(list(set(cluster_nodes)))
        self.secret_key = secret_key.encode("utf-8")

        self.n = len(self.cluster_nodes)
        # Допустимое число сбоев: f = (n - 1) // 3
        self.f = (self.n - 1) // 3 if self.n >= 4 else 0
        # Кворум: 2f + 1 (для n=4, f=1 -> quorum=3)
        self.quorum_size = 2 * self.f + 1 if self.f > 0 else (self.n // 2 + 1)

        self.current_epoch = 1
        self.sequence_number = 0
        self.phase = BFTPhase.IDLE

        self.active_proposal: Optional[ReceiptProposal] = None
        self._prepare_votes: Dict[str, BFTVote] = {}
        self._commit_votes: Dict[str, BFTVote] = {}
        self._committed_receipts: Dict[int, Dict[str, Any]] = {}

        self._stats = {
            "proposals_initiated": 0,
            "consensus_reached": 0,
            "byzantine_rejected": 0,
            "quorum_failures": 0,
        }

    def sign_digest(self, digest: bytes) -> str:
        """Генерация HMAC-подписи для квитанции или голоса."""
        return hmac.new(self.secret_key, digest, hashlib.sha256).hexdigest()

    def verify_signature(self, voter_id: str, digest: bytes, signature: str) -> bool:
        """Проверка подписи узла кластера."""
        if voter_id not in self.cluster_nodes:
            return False
        expected = hmac.new(self.secret_key, digest, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def propose(self, merkle_root: str, checkpoints_count: int) -> ReceiptProposal:
        """Инициализация новой квитанции лидером раунда."""
        self.sequence_number += 1
        self.phase = BFTPhase.PRE_PREPARED
        self._prepare_votes.clear()
        self._commit_votes.clear()

        prop = ReceiptProposal(
            sequence_number=self.sequence_number,
            epoch=self.current_epoch,
            merkle_root=merkle_root,
            checkpoints_count=checkpoints_count,
            timestamp=time.time(),
            proposer_id=self.node_id,
        )
        prop.signature = self.sign_digest(prop.compute_digest())
        self.active_proposal = prop
        self._stats["proposals_initiated"] += 1

        # Лидер автоматически отдает свой голос PREPARE
        leader_vote = BFTVote(
            phase="PREPARE",
            sequence_number=prop.sequence_number,
            epoch=prop.epoch,
            merkle_root=prop.merkle_root,
            voter_id=self.node_id,
        )
        leader_vote.signature = self.sign_digest(leader_vote.compute_digest())
        self._prepare_votes[self.node_id] = leader_vote

        return prop

    def handle_pre_prepare(
        self,
        proposal: ReceiptProposal,
        local_expected_merkle: Optional[str] = None,
    ) -> Optional[BFTVote]:
        """Обработка входящего предложения PRE_PREPARE от лидера."""
        # Проверка подписи лидера
        if not self.verify_signature(proposal.proposer_id, proposal.compute_digest(), proposal.signature):
            self._stats["byzantine_rejected"] += 1
            return None

        # Проверка согласованности с локальным деревом (если передано)
        if local_expected_merkle and local_expected_merkle != proposal.merkle_root:
            self._stats["byzantine_rejected"] += 1
            return None

        self.sequence_number = proposal.sequence_number
        self.active_proposal = proposal
        self.phase = BFTPhase.PRE_PREPARED
        self._prepare_votes.clear()
        self._commit_votes.clear()

        # Формируем и подписываем голос PREPARE
        vote = BFTVote(
            phase="PREPARE",
            sequence_number=proposal.sequence_number,
            epoch=proposal.epoch,
            merkle_root=proposal.merkle_root,
            voter_id=self.node_id,
        )
        vote.signature = self.sign_digest(vote.compute_digest())
        self._prepare_votes[self.node_id] = vote
        return vote

    def handle_prepare(self, vote: BFTVote) -> Optional[BFTVote]:
        """Обработка голоса PREPARE от узла кластера."""
        if not self.active_proposal:
            return None

        if vote.sequence_number != self.active_proposal.sequence_number:
            return None

        if not self.verify_signature(vote.voter_id, vote.compute_digest(), vote.signature):
            self._stats["byzantine_rejected"] += 1
            return None

        # Проверка на совпадение Merkle Root (византийский узел может слать другой корень)
        if vote.merkle_root != self.active_proposal.merkle_root:
            self._stats["byzantine_rejected"] += 1
            return None

        self._prepare_votes[vote.voter_id] = vote

        # Если кворум PREPARE набран и мы еще не в PREPARED
        if len(self._prepare_votes) >= self.quorum_size and self.phase == BFTPhase.PRE_PREPARED:
            self.phase = BFTPhase.PREPARED
            commit_vote = BFTVote(
                phase="COMMIT",
                sequence_number=self.active_proposal.sequence_number,
                epoch=self.active_proposal.epoch,
                merkle_root=self.active_proposal.merkle_root,
                voter_id=self.node_id,
            )
            commit_vote.signature = self.sign_digest(commit_vote.compute_digest())
            self._commit_votes[self.node_id] = commit_vote
            return commit_vote

        return None

    def handle_commit(self, vote: BFTVote) -> bool:
        """Обработка голоса COMMIT от узла кластера."""
        if not self.active_proposal:
            return False

        if vote.sequence_number != self.active_proposal.sequence_number:
            return False

        if not self.verify_signature(vote.voter_id, vote.compute_digest(), vote.signature):
            self._stats["byzantine_rejected"] += 1
            return False

        if vote.merkle_root != self.active_proposal.merkle_root:
            self._stats["byzantine_rejected"] += 1
            return False

        self._commit_votes[vote.voter_id] = vote

        # Если кворум COMMIT набран
        if len(self._commit_votes) >= self.quorum_size and self.phase != BFTPhase.COMMITTED:
            self.phase = BFTPhase.COMMITTED
            self._committed_receipts[self.sequence_number] = {
                "sequence_number": self.sequence_number,
                "epoch": self.active_proposal.epoch,
                "merkle_root": self.active_proposal.merkle_root,
                "checkpoints_count": self.active_proposal.checkpoints_count,
                "committed_at": time.time(),
                "quorum_size": self.quorum_size,
                "signatures_collected": len(self._commit_votes),
            }
            self._stats["consensus_reached"] += 1
            return True

        return False

    def propose_membership_change(self, action: str, target_node_id: str) -> Dict[str, Any]:
        """Формирование предложения изменения состава валидаторов (ADD_NODE / REMOVE_NODE / R8)."""
        if action not in ("ADD_NODE", "REMOVE_NODE"):
            raise ValueError(f"Invalid membership action: {action}")
        self.sequence_number += 1
        digest = hashlib.sha256(f"{action}:{target_node_id}:{self.current_epoch}:{self.sequence_number}".encode("utf-8")).digest()
        sig = self.sign_digest(digest)
        return {
            "type": "MEMBERSHIP_PROPOSAL",
            "action": action,
            "target_node_id": target_node_id,
            "epoch": self.current_epoch,
            "sequence_number": self.sequence_number,
            "proposer_id": self.node_id,
            "signature": sig,
        }

    def apply_membership_change(
        self,
        action: str,
        target_node_id: str,
        commit_signatures: Dict[str, str],
    ) -> bool:
        """
        Применение изменения состава узлов кластера при наличии кворума подписей (2f_old + 1).
        Увеличивает эпоху, пересчитывает N, f и quorum_size без остановки работы (R8).
        """
        valid_signatures = 0
        digest = hashlib.sha256(f"{action}:{target_node_id}:{self.current_epoch}:{self.sequence_number}".encode("utf-8")).digest()
        for voter_id, sig in commit_signatures.items():
            if voter_id in self.cluster_nodes:
                if self.verify_signature(voter_id, digest, sig):
                    valid_signatures += 1

        if valid_signatures < self.quorum_size:
            self._stats["quorum_failures"] += 1
            return False

        nodes_set = set(self.cluster_nodes)
        if action == "ADD_NODE":
            nodes_set.add(target_node_id)
        elif action == "REMOVE_NODE":
            nodes_set.discard(target_node_id)

        self.cluster_nodes = sorted(list(nodes_set))
        self.n = len(self.cluster_nodes)
        self.f = (self.n - 1) // 3 if self.n >= 4 else 0
        self.quorum_size = 2 * self.f + 1 if self.f > 0 else (self.n // 2 + 1)
        self.current_epoch += 1
        return True

    def is_committed(self, sequence_number: int) -> bool:
        return sequence_number in self._committed_receipts

    def get_committed_receipt(self, sequence_number: int) -> Optional[Dict[str, Any]]:
        return self._committed_receipts.get(sequence_number)

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "cluster_nodes_count": self.n,
            "byzantine_tolerance_f": self.f,
            "quorum_size": self.quorum_size,
            "epoch": self.current_epoch,
            "phase": self.phase.value,
            "sequence_number": self.sequence_number,
            "committed_count": len(self._committed_receipts),
            "stats": self._stats,
        }
