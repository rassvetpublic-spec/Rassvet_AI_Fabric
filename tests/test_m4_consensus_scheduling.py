"""Unit and adversarial tests for Milestone M4 (R7, R8, R10): Distributed Scheduling & Consensus.

Covers:
- R7: WeightedLoadBalancer & Work-Stealing in DistributedWorkerPool
- R8: Dynamic BFT Cluster Membership Reconfiguration (ADD_NODE / REMOVE_NODE, epoch shift)
- R10: Merkle Mountain Range (MMR) & zk-Receipt Compression (O(log N) proofs, 32-byte bagged root)
"""

import hashlib
import pytest
from unittest.mock import MagicMock

from rai_fabric.distributed_pool import DistributedWorkerPool, WeightedLoadBalancer
from rai_fabric.bft_consensus import BFTConsensusNode, BFTPhase
from rai_fabric.tri_tower_sync import MerkleMountainRange, MMRProof


# ==============================================================================
# R7: Weighted Load Balancing & Work-Stealing Tests
# ==============================================================================

def test_weighted_load_balancer_scoring():
    # High VRAM worker (16GB) vs Low VRAM worker (4GB) with same active tasks
    score_high = WeightedLoadBalancer.score_worker(vram_free_mb=16000.0, compute_power=1.0, active_tasks=0, task_tokens=1024)
    score_low = WeightedLoadBalancer.score_worker(vram_free_mb=4000.0, compute_power=1.0, active_tasks=0, task_tokens=1024)
    assert score_high > score_low

    # Worker with higher active tasks gets penalized
    score_busy = WeightedLoadBalancer.score_worker(vram_free_mb=16000.0, compute_power=1.0, active_tasks=5, task_tokens=1024)
    assert score_busy < score_high

    # Heavy task token count adds appropriate penalty
    score_heavy = WeightedLoadBalancer.score_worker(vram_free_mb=16000.0, compute_power=1.0, active_tasks=0, task_tokens=16384)
    assert score_heavy < score_high


def test_work_stealing_between_workers():
    pool = DistributedWorkerPool()
    pool.register_worker("worker-1", vram_free_mb=12000.0, compute_power=1.0)
    pool.register_worker("worker-2", vram_free_mb=8000.0, compute_power=1.0)

    # Worker-1 has 3 pending tasks
    pool.enqueue_worker_task("worker-1", {"task_id": "t-1", "prompt": "p1"})
    pool.enqueue_worker_task("worker-1", {"task_id": "t-2", "prompt": "p2"})
    pool.enqueue_worker_task("worker-1", {"task_id": "t-3", "prompt": "p3"})

    # Worker-2 is idle and steals work from Worker-1
    stolen = pool.steal_work("worker-2")
    assert stolen is not None
    assert stolen["task_id"] == "t-3"  # Stolen from tail

    # Worker-1 now has 2 tasks left
    assert len(pool._workers["worker-1"]["pending_queue"]) == 2


# ==============================================================================
# R8: Dynamic BFT Membership Reconfiguration Tests
# ==============================================================================

def test_bft_dynamic_membership_add_and_remove():
    initial_nodes = ["node-0", "node-1", "node-2", "node-3"]
    key = "test_cluster_secret"
    nodes = {nid: BFTConsensusNode(nid, initial_nodes, secret_key=key) for nid in initial_nodes}

    # Initial cluster state: N=4, f=1, quorum=3
    assert nodes["node-0"].n == 4
    assert nodes["node-0"].f == 1
    assert nodes["node-0"].quorum_size == 3
    assert nodes["node-0"].current_epoch == 1

    # Leader node-0 proposes ADD_NODE "node-4"
    prop = nodes["node-0"].propose_membership_change("ADD_NODE", "node-4")
    assert prop["type"] == "MEMBERSHIP_PROPOSAL"
    assert prop["action"] == "ADD_NODE"

    # Collect 3 signatures (quorum) from node-0, node-1, node-2
    digest = hashlib.sha256(f"ADD_NODE:node-4:{prop['epoch']}:{prop['sequence_number']}".encode("utf-8")).digest()
    signatures = {
        "node-0": nodes["node-0"].sign_digest(digest),
        "node-1": nodes["node-1"].sign_digest(digest),
        "node-2": nodes["node-2"].sign_digest(digest),
    }

    # Apply membership change on all nodes
    for nid, node in nodes.items():
        node.sequence_number = prop["sequence_number"]
        ok = node.apply_membership_change("ADD_NODE", "node-4", signatures)
        assert ok is True
        assert node.current_epoch == 2
        assert "node-4" in node.cluster_nodes
        assert node.n == 5

    # Insufficient signatures fail-closed
    bad_signatures = {"node-0": nodes["node-0"].sign_digest(digest)}
    prop_fail = nodes["node-0"].propose_membership_change("REMOVE_NODE", "node-4")
    digest_fail = hashlib.sha256(f"REMOVE_NODE:node-4:{prop_fail['epoch']}:{prop_fail['sequence_number']}".encode("utf-8")).digest()
    ok_fail = nodes["node-0"].apply_membership_change("REMOVE_NODE", "node-4", bad_signatures)
    assert ok_fail is False


# ==============================================================================
# R10: Merkle Mountain Range (MMR) & zk-Receipt Tests
# ==============================================================================

def test_mmr_append_and_bagged_root():
    mmr = MerkleMountainRange()
    leaf_hashes = [hashlib.sha256(f"checkpoint_{i}".encode("utf-8")).hexdigest() for i in range(7)]

    for h in leaf_hashes:
        mmr.append(h)

    assert mmr.leaf_count == 7
    # 7 leaves = 4 + 2 + 1 (binary representation has 3 peaks)
    peaks = mmr.get_peaks()
    assert len(peaks) == 3

    root = mmr.get_root()
    assert len(root) == 64
    assert isinstance(root, str)


def test_mmr_inclusion_proof_and_verification():
    mmr = MerkleMountainRange()
    leaf_hashes = [hashlib.sha256(f"receipt_record_{i}".encode("utf-8")).hexdigest() for i in range(15)]

    for h in leaf_hashes:
        mmr.append(h)

    root = mmr.get_root()

    # Verify inclusion proofs for multiple leaves
    for idx in [0, 3, 7, 14]:
        proof = mmr.get_proof(idx)
        assert proof.leaf_index == idx
        assert proof.leaf_hash == leaf_hashes[idx]

        is_valid = MerkleMountainRange.verify_proof(root, leaf_hashes[idx], proof)
        assert is_valid is True

        # Tampered leaf hash must fail verification
        tampered_hash = hashlib.sha256(b"tampered").hexdigest()
        is_tampered_valid = MerkleMountainRange.verify_proof(root, tampered_hash, proof)
        assert is_tampered_valid is False
