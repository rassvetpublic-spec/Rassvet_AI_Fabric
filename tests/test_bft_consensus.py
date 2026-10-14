"""Тесты для Stage R32: Византийский консенсус квитанций Трёх Башен (src/rai_fabric/bft_consensus.py)."""

import pytest
from rai_fabric.bft_consensus import BFTConsensusNode, BFTPhase, ReceiptProposal, BFTVote


@pytest.fixture
def cluster_setup():
    cluster_nodes = ["node_0", "node_1", "node_2", "node_3"]
    secret = "shared_test_cluster_secret_bpr5"
    nodes = {nid: BFTConsensusNode(nid, cluster_nodes, secret) for nid in cluster_nodes}
    return nodes, cluster_nodes


def test_bft_consensus_happy_path(cluster_setup):
    nodes, cluster_nodes = cluster_setup
    leader = nodes["node_0"]
    merkle_root = "a3f3f20596f2f81b45cad6547c660b5123403c1927a647fa2828653939ade39f"
    checkpoints_count = 145

    # 1. Фаза PRE_PREPARE: Лидер инициирует предложение
    proposal = leader.propose(merkle_root, checkpoints_count)
    assert leader.phase == BFTPhase.PRE_PREPARED
    assert proposal.sequence_number == 1

    # Валидаторы принимают предложение и генерируют голоса PREPARE
    prepare_votes = [leader._prepare_votes[leader.node_id]]
    for nid in ["node_1", "node_2", "node_3"]:
        v = nodes[nid].handle_pre_prepare(proposal, local_expected_merkle=merkle_root)
        assert v is not None
        assert v.phase == "PREPARE"
        prepare_votes.append(v)

    # 2. Фаза PREPARE: Все обмениваются голосами PREPARE
    commit_votes = []
    for voter in nodes.values():
        for pv in prepare_votes:
            cv = voter.handle_prepare(pv)
            if cv:
                commit_votes.append(cv)

    # Все узлы должны перейти в фазу PREPARED и отправить голос COMMIT
    for voter in nodes.values():
        assert voter.phase in (BFTPhase.PREPARED, BFTPhase.COMMITTED)

    # 3. Фаза COMMIT: Все обмениваются голосами COMMIT
    for voter in nodes.values():
        for cv in commit_votes:
            voter.handle_commit(cv)

    # Все узлы должны зафиксировать квитанцию в COMMITTED
    for nid, node in nodes.items():
        assert node.phase == BFTPhase.COMMITTED
        assert node.is_committed(1) is True
        receipt = node.get_committed_receipt(1)
        assert receipt is not None
        assert receipt["merkle_root"] == merkle_root
        assert receipt["checkpoints_count"] == 145


def test_bft_consensus_with_one_byzantine_fault(cluster_setup):
    nodes, cluster_nodes = cluster_setup
    leader = nodes["node_0"]
    merkle_root = "a3f3f20596f2f81b45cad6547c660b5123403c1927a647fa2828653939ade39f"
    proposal = leader.propose(merkle_root, 145)

    # Честные узлы голосуют правильно
    prepare_votes = [leader._prepare_votes[leader.node_id]]
    for nid in ["node_1", "node_2"]:
        v = nodes[nid].handle_pre_prepare(proposal, local_expected_merkle=merkle_root)
        prepare_votes.append(v)

    # node_3 — византийский (шлёт фальшивый Merkle Root)
    rogue_vote = BFTVote(
        phase="PREPARE",
        sequence_number=proposal.sequence_number,
        epoch=proposal.epoch,
        merkle_root="0000000000000000000000000000000000000000000000000000000000000000",
        voter_id="node_3",
    )
    rogue_vote.signature = nodes["node_3"].sign_digest(rogue_vote.compute_digest())
    prepare_votes.append(rogue_vote)

    # Обмен голосами PREPARE среди честных узлов
    commit_votes = []
    for nid in ["node_0", "node_1", "node_2"]:
        node = nodes[nid]
        for pv in prepare_votes:
            cv = node.handle_prepare(pv)
            if cv:
                commit_votes.append(cv)

    # Кворум (3 из 4) набран честными узлами
    for nid in ["node_0", "node_1", "node_2"]:
        node = nodes[nid]
        assert node.phase == BFTPhase.PREPARED
        # Проверяем, что византийский голос был отклонен
        assert node.get_metrics()["stats"]["byzantine_rejected"] >= 1

    # Завершение фазы COMMIT
    for nid in ["node_0", "node_1", "node_2"]:
        node = nodes[nid]
        for cv in commit_votes:
            node.handle_commit(cv)
        assert node.is_committed(1) is True


def test_bft_consensus_quorum_failure(cluster_setup):
    nodes, cluster_nodes = cluster_setup
    leader = nodes["node_0"]
    proposal = leader.propose("test_root", 10)

    # Допустим, отвечает только 1 валидатор (всего 2 голоса из 4, кворум 3 не набран)
    pv0 = leader._prepare_votes[leader.node_id]
    pv1 = nodes["node_1"].handle_pre_prepare(proposal)

    cv0 = leader.handle_prepare(pv1)
    cv1 = nodes["node_1"].handle_prepare(pv0)

    # Кворум PREPARE не достигнут — голоса COMMIT не генерируются
    assert cv0 is None
    assert cv1 is None
    assert leader.phase == BFTPhase.PRE_PREPARED
    assert leader.is_committed(1) is False


def test_bft_signature_verification_failure(cluster_setup):
    nodes, _ = cluster_setup
    leader = nodes["node_0"]
    proposal = leader.propose("test_root", 10)

    # Подделываем подпись
    proposal.signature = "bad_forged_signature_hex"
    v = nodes["node_1"].handle_pre_prepare(proposal)
    assert v is None
    assert nodes["node_1"].get_metrics()["stats"]["byzantine_rejected"] == 1


def test_bft_unregistered_node_rejected(cluster_setup):
    nodes, _ = cluster_setup
    leader = nodes["node_0"]
    proposal = leader.propose("test_root", 10)

    alien_vote = BFTVote(
        phase="PREPARE",
        sequence_number=1,
        epoch=1,
        merkle_root="test_root",
        voter_id="alien_untrusted_node",
    )
    alien_vote.signature = "some_signature"

    cv = leader.handle_prepare(alien_vote)
    assert cv is None
    assert leader.get_metrics()["stats"]["byzantine_rejected"] == 1
