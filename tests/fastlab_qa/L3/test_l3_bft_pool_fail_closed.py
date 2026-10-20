"""L3 isolated adversarial consensus and worker-pool contracts; no live GPU/Fleet."""
import math
import pytest

from rai_fabric.bft_consensus import BFTConsensusNode, BFTPhase, BFTVote
from rai_fabric.distributed_pool import DistributedWorkerPool
from transport.ipc_channel import TransportError, TransportMessageEnvelope, TransportStatus


def _signed_vote(node, proposal, phase="PREPARE", epoch=None):
    v = BFTVote(phase=phase, sequence_number=proposal.sequence_number,
                epoch=proposal.epoch if epoch is None else epoch,
                merkle_root=proposal.merkle_root, voter_id=node.node_id)
    v.signature = node.sign_digest(v.compute_digest())
    return v


@pytest.mark.parametrize("phase,epoch_offset", [("COMMIT", 0), ("PREPARE", 1)])
def test_prepare_denies_wrong_phase_or_epoch(phase, epoch_offset):
    ids = ["a", "b", "c", "d"]
    nodes = {i: BFTConsensusNode(i, ids, secret_key="synthetic") for i in ids}
    leader = nodes["a"]
    prop = leader.propose("verified-root", 2)
    for i in ("b", "c"):
        vote = _signed_vote(nodes[i], prop, phase=phase, epoch=prop.epoch+epoch_offset)
        assert leader.handle_prepare(vote) is None
    assert leader.phase == BFTPhase.PRE_PREPARED
    assert len(leader._prepare_votes) == 1


def test_commit_quorum_denied_before_prepared():
    ids = ["a", "b", "c", "d"]
    nodes = {i: BFTConsensusNode(i, ids, secret_key="synthetic") for i in ids}
    leader = nodes["a"]
    prop = leader.propose("verified-root", 1)
    for i in ("a", "b", "c"):
        assert leader.handle_commit(_signed_vote(nodes[i], prop, phase="COMMIT")) is False
    assert leader.phase == BFTPhase.PRE_PREPARED
    assert leader.get_committed_receipt(prop.sequence_number) is None


def test_preprepare_replay_same_sequence_denied():
    ids = ["a", "b", "c", "d"]
    nodes = {i: BFTConsensusNode(i, ids, secret_key="synthetic") for i in ids}
    prop = nodes["a"].propose("stable-root", 1)
    follower = nodes["b"]
    assert follower.handle_pre_prepare(prop) is not None
    old_seq = follower.sequence_number
    assert follower.handle_pre_prepare(prop) is None
    assert follower.sequence_number == old_seq


def test_membership_rejects_unrecognized_action_and_empty_target():
    ids = ["a", "b", "c", "d"]
    nodes = {i: BFTConsensusNode(i, ids, secret_key="synthetic") for i in ids}
    n = nodes["a"]
    with pytest.raises(ValueError):
        n.propose_membership_change("ADD_NODE", "")
    digest = __import__("hashlib").sha256(b"INVALID:ghost:1:1").digest()
    n.sequence_number = 1
    votes = {i: nodes[i].sign_digest(digest) for i in ("a", "b", "c")}
    assert n.apply_membership_change("INVALID", "ghost", votes) is False
    assert n.current_epoch == 1


class _SyntheticReplyTransport:
    status = TransportStatus.CONNECTED
    def __init__(self, kind):
        self.kind = kind
        self.command = None
    def is_connected(self):
        return True
    def send(self, envelope):
        self.command = envelope
        return True
    def receive(self, timeout=1.0):
        if self.kind == "wrong_ref":
            return TransportMessageEnvelope.create(payload_type="response",
                payload={"ref_id":"unrelated-request", "reply":{"text":"result","eval_count":3}})
        env = TransportMessageEnvelope.create(payload_type="response",
            payload={"ref_id":self.command.message_id,"reply":{"text":"result","eval_count":3}})
        env.payload["reply"]["text"] = "tampered"
        return env


@pytest.mark.parametrize("kind", ["wrong_ref", "tampered"])
def test_pool_does_not_complete_unrelated_or_tampered_reply(kind):
    transport = _SyntheticReplyTransport(kind)
    pool = DistributedWorkerPool(gpu_transport=transport)
    pool.register_worker("w1")
    with pytest.raises(TransportError):
        pool.dispatch_inference_task("synthetic", task_id="t1")
    stats = pool.get_pool_status()["stats"]
    assert stats["completed_tasks"] == 0
    assert stats["failed_tasks"] == 1


def test_pool_limits_pending_queue_and_rejects_nan_worker():
    transport = _SyntheticReplyTransport("wrong_ref")
    pool = DistributedWorkerPool(gpu_transport=transport, max_queue_depth=1)
    assert pool.register_worker("nan", vram_free_mb=float("nan")) is False
    assert pool.register_worker("w1") is True
    assert pool.enqueue_worker_task("w1", {"task_id":"first"}) is True
    assert pool.enqueue_worker_task("w1", {"task_id":"second"}) is False
    assert len(pool.get_pool_status()["workers"][0]["pending_queue"]) == 1
