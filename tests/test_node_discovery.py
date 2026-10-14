# -*- coding: utf-8 -*-
"""
tests/test_node_discovery.py - 100% offline-safe тесты децентрализованного реестра NodeDiscoveryRegistry (Stage R27).
"""

from __future__ import annotations

import json
import time
import pytest
from rai_fabric.node_discovery import NodeDiscoveryRegistry


class TestNodeDiscoveryRegistry:
    def test_register_and_get_node(self) -> None:
        registry = NodeDiscoveryRegistry(cluster_id="test-cluster")
        assert registry.register_node(
            node_id="gpu-node-01",
            role="COMPUTE_NODE",
            endpoint="http://127.0.0.1:11434",
            capabilities=["inference", "cuda"],
            resources={"vram_mb": 16303},
        )

        node = registry.get_node("gpu-node-01")
        assert node is not None
        assert node["role"] == "COMPUTE_NODE"
        assert node["status"] == "ONLINE"
        assert node["resources"]["vram_mb"] == 16303
        assert "inference" in node["capabilities"]

    def test_heartbeat_updates_timestamp_and_resources(self) -> None:
        registry = NodeDiscoveryRegistry()
        registry.register_node("node-01")
        initial_node = registry.get_node("node-01")
        assert initial_node is not None
        t0 = initial_node["last_heartbeat"]

        time.sleep(0.01)
        assert registry.heartbeat("node-01", resources={"temperature_c": 52})
        updated_node = registry.get_node("node-01")
        assert updated_node is not None
        assert updated_node["last_heartbeat"] > t0
        assert updated_node["resources"]["temperature_c"] == 52

        # Heartbeat on non-existent node returns False
        assert registry.heartbeat("non-existent") is False

    def test_list_active_nodes_filters(self) -> None:
        registry = NodeDiscoveryRegistry()
        registry.register_node("compute-01", role="COMPUTE_NODE", capabilities=["inference"])
        registry.register_node("storage-01", role="STORAGE_NODE", capabilities=["checkpoints"])
        registry.register_node("coord-01", role="COORDINATOR_NODE", capabilities=["scheduler"])

        compute_nodes = registry.list_active_nodes(role="COMPUTE_NODE")
        assert len(compute_nodes) == 1
        assert compute_nodes[0]["node_id"] == "compute-01"

        ckpt_nodes = registry.list_active_nodes(capability="checkpoints")
        assert len(ckpt_nodes) == 1
        assert ckpt_nodes[0]["node_id"] == "storage-01"

    def test_evict_stale_nodes(self) -> None:
        registry = NodeDiscoveryRegistry()
        registry.register_node("active-node", lease_ttl_seconds=10.0)
        registry.register_node("stale-node", lease_ttl_seconds=0.01)

        # Force staleness on stale-node
        with registry._lock:
            registry._nodes["stale-node"]["last_heartbeat"] = time.time() - 100.0

        evicted = registry.evict_stale_nodes(max_staleness_seconds=50.0)
        assert "stale-node" in evicted
        assert "active-node" not in evicted

        assert registry.get_node("stale-node") is None
        assert registry.get_node("active-node") is not None

    def test_get_cluster_topology(self) -> None:
        registry = NodeDiscoveryRegistry(cluster_id="fleet-alpha")
        registry.register_node("c1", role="COMPUTE_NODE")
        registry.register_node("c2", role="COMPUTE_NODE")
        registry.register_node("s1", role="STORAGE_NODE")

        topo = registry.get_cluster_topology()
        assert topo["cluster_id"] == "fleet-alpha"
        assert topo["total_nodes"] == 3
        assert topo["online_nodes"] == 3
        assert topo["role_distribution"]["COMPUTE_NODE"] == 2
        assert topo["role_distribution"]["STORAGE_NODE"] == 1

    def test_discover_local_gpu_node_mocked(self) -> None:
        from unittest.mock import patch, MagicMock
        registry = NodeDiscoveryRegistry()

        mock_payload = {
            "node_id": "node-gpu-rtx5070ti-01",
            "role": "COMPUTE_NODE",
            "capabilities": ["inference", "code-eval"],
            "resources": {"gpu_model": "NVIDIA GeForce RTX 5070 Ti", "vram_total_mb": 16303},
        }

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            node = registry.discover_local_gpu_node("http://127.0.0.1:11434")

        assert node is not None
        assert node["node_id"] == "node-gpu-rtx5070ti-01"
        assert node["role"] == "COMPUTE_NODE"
        assert node["resources"]["gpu_model"] == "NVIDIA GeForce RTX 5070 Ti"
        assert registry.get_node("node-gpu-rtx5070ti-01") is not None
