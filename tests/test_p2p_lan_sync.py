# -*- coding: utf-8 -*-
"""
tests.test_p2p_lan_sync - Тесты кросс-хостовой P2P Merkle-синхронизации и LAN-обнаружения (Stage R29 / Class C-Z).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / Offline-Safe.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

from rai_fabric.p2p_lan_sync import (
    CrossHostP2PSyncManager,
    LanBeacon,
    LanPeerDiscovery,
)


def test_lan_beacon_serialization_roundtrip():
    """Проверка сериализации и парсинга маяка узла LanBeacon."""
    beacon = LanBeacon(
        node_id="test-host-rtx5070ti",
        host="192.168.1.100",
        port=11434,
        merkle_root="a3f3f20596f2f81b45cad6547c660b5123403c1927a647fa2828653939ade39f",
        checkpoints_count=145,
        capabilities=["inference", "merkle-sync", "multi-model"],
        timestamp=1728950400.0,
        ttl_seconds=45.0,
    )

    d = beacon.to_dict()
    assert d["node_id"] == "test-host-rtx5070ti"
    assert d["port"] == 11434
    assert d["merkle_root"].startswith("a3f3f2")
    assert d["ttl_seconds"] == 45.0

    raw = beacon.to_bytes()
    restored = LanBeacon.from_bytes(raw)
    assert restored is not None
    assert restored.node_id == beacon.node_id
    assert restored.host == beacon.host
    assert restored.port == beacon.port
    assert restored.merkle_root == beacon.merkle_root
    assert restored.checkpoints_count == beacon.checkpoints_count


def test_lan_peer_discovery_ttl_and_expiry():
    """Проверка регистрации пиров и очистки по TTL."""
    discovery = LanPeerDiscovery(ttl_seconds=0.1)

    beacon1 = LanBeacon(
        node_id="peer-node-01",
        host="192.168.1.101",
        port=11434,
        merkle_root="root-hash-01",
        checkpoints_count=10,
        ttl_seconds=0.1,
    )
    discovery.register_peer(beacon1)

    active = discovery.get_active_peers()
    assert len(active) == 1
    assert active[0]["node_id"] == "peer-node-01"

    # Ждём истечения TTL
    time.sleep(0.15)
    purged = discovery.purge_expired_peers()
    assert purged == 1
    assert len(discovery.get_active_peers()) == 0


def test_cross_host_parity_in_sync():
    """Проверка детекции 100% паритета при совпадении Merkle-корней хостов."""
    manager = CrossHostP2PSyncManager(node_id="local-coordinator")
    local_offer = manager.exchange.create_sync_offer()
    local_root = local_offer["merkle_root"]

    # Идентичный оффер от удалённого хоста
    remote_offer = {
        "protocol": "BPR5_NEXTGEN_R3.3",
        "stage": "STAGE_R29_LAN_P2P",
        "node_id": "remote-workstation-02",
        "merkle_root": local_root,
        "checkpoints_count": local_offer["checkpoints_count"],
        "items_manifest": local_offer["items_manifest"],
        "timestamp": time.time(),
    }

    result = manager.reconcile_with_peer(remote_offer)
    assert result["status"] == "IN_SYNC"
    assert result["is_parity"] is True
    assert result["reconciled_count"] == 0
    assert result["merkle_root"] == local_root


def test_cross_host_parity_delta_and_reconciliation(tmp_path):
    """Проверка детекции расхождений и антиэнтропийного разрешения дельты чекпойнтов."""
    manager = CrossHostP2PSyncManager(repo_root=tmp_path, node_id="host-local")

    # Искусственный оффер с расходящимся корнем и дополнительным чекпойнтом
    cp_name = "099_new_remote_checkpoint.json"
    cp_content = {"version": "1.0", "status": "CONFIRMED"}
    raw_cp = json.dumps(cp_content, sort_keys=True).encode("utf-8")
    cp_hash = hashlib.sha256(raw_cp).hexdigest()

    remote_offer = {
        "protocol": "BPR5_NEXTGEN_R3.3",
        "stage": "STAGE_R29_LAN_P2P",
        "node_id": "remote-host-b",
        "merkle_root": "divergent-remote-root-abc12345",
        "checkpoints_count": 5,
        "items_manifest": {
            cp_name: cp_hash,
        },
        "timestamp": time.time(),
    }

    # Мок-функция получения недостающего чекпойнта от пира
    def mock_fetch(name: str):
        if name == cp_name:
            return cp_content
        return None

    result = manager.reconcile_with_peer(remote_offer, fetch_checkpoint_fn=mock_fetch)
    assert result["status"] == "RECONCILED"
    assert result["is_parity"] is False
    assert cp_name in result["reconciled_items"]
    assert len(result["errors"]) == 0


def test_fleet_lan_topology_mapping():
    """Проверка построения сводной топологии сети и сетевого процента паритета."""
    manager = CrossHostP2PSyncManager(node_id="primary-host")
    local_offer = manager.exchange.create_sync_offer()
    local_root = local_offer["merkle_root"]

    # Регистрируем синхронизированный пир
    manager.discovery.register_synthetic_peer({
        "node_id": "peer-synced-1",
        "merkle_root": local_root,
        "checkpoints_count": local_offer["checkpoints_count"],
        "ttl_seconds": 60,
    })

    # Регистрируем отстающий пир
    manager.discovery.register_synthetic_peer({
        "node_id": "peer-lagging-2",
        "merkle_root": "different-root-777",
        "checkpoints_count": 10,
        "ttl_seconds": 60,
    })

    topology = manager.get_fleet_lan_topology()
    assert topology["stage"] == "STAGE_R29_LAN_P2P"
    assert topology["total_nodes"] == 3  # self + 2 peers
    assert topology["synced_nodes"] == 2  # self + peer-synced-1
    assert topology["network_parity_pct"] == pytest.approx(66.7, abs=0.1)

    node_map = {n["node_id"]: n for n in topology["nodes"]}
    assert node_map["primary-host"]["is_self"] is True
    assert node_map["peer-synced-1"]["is_synced"] is True
    assert node_map["peer-lagging-2"]["is_synced"] is False
