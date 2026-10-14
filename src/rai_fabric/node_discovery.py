# -*- coding: utf-8 -*-
"""
rai_fabric.node_discovery - Децентрализованный реестр и сетевой шлюз Discovery узлов флота (Stage R27 / R0.7).

Обеспечивает:
  1. Динамическую регистрацию вычислительных (COMPUTE_NODE), координационных (COORDINATOR_NODE)
     и узлов хранения (STORAGE_NODE);
  2. Lease-based Heartbeat отслеживание доступности узлов без нагрузки на диск (Zero SSD Wear);
  3. Автоматическую детекцию устаревших узлов и перевод в DEGRADED / EVICTED;
  4. Фильтрацию активных узлов по ролям и возможностям (capabilities) для балансировщика;
  5. Формирование топологического среза кластера флота для супервизора и UI-панелей.

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R27 / Rassvet_AI_Fabric.
"""

from __future__ import annotations

__version__ = "1.0.0"

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("raif.node_discovery")


class NodeDiscoveryRegistry:
    """Координационный реестр топологии и сетевых узлов флота."""

    VALID_ROLES = {"COMPUTE_NODE", "STORAGE_NODE", "COORDINATOR_NODE"}
    DEFAULT_LEASE_TTL = 30.0

    def __init__(self, cluster_id: str = "raif-fleet-main") -> None:
        self.cluster_id = cluster_id
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def register_node(
        self,
        node_id: str,
        role: str = "COMPUTE_NODE",
        endpoint: str = "http://127.0.0.1:11434",
        capabilities: Optional[List[str]] = None,
        resources: Optional[Dict[str, Any]] = None,
        lease_ttl_seconds: float = DEFAULT_LEASE_TTL,
    ) -> bool:
        """Регистрация нового узла кластера или обновление существующего."""
        if not node_id:
            return False

        assigned_role = role if role in self.VALID_ROLES else "COMPUTE_NODE"
        now = time.time()

        with self._lock:
            self._nodes[node_id] = {
                "node_id": node_id,
                "role": assigned_role,
                "endpoint": endpoint,
                "capabilities": capabilities or ["inference"],
                "resources": resources or {},
                "lease_ttl_seconds": lease_ttl_seconds,
                "registered_at": now,
                "last_heartbeat": now,
                "status": "ONLINE",
            }
            logger.info("Node registered in cluster [%s]: %s (%s)", self.cluster_id, node_id, assigned_role)
            return True

    def heartbeat(
        self,
        node_id: str,
        resources: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Обновление пульса и телеметрии зарегистрированного узла."""
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return False
            node["last_heartbeat"] = time.time()
            node["status"] = "ONLINE"
            if resources:
                node["resources"].update(resources)
            return True

    def unregister_node(self, node_id: str) -> bool:
        """Явное исключение узла из реестра."""
        with self._lock:
            if node_id in self._nodes:
                del self._nodes[node_id]
                logger.info("Node unregistered from cluster [%s]: %s", self.cluster_id, node_id)
                return True
            return False

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Получение копии карточки узла."""
        with self._lock:
            node = self._nodes.get(node_id)
            return dict(node) if node else None

    def list_active_nodes(
        self,
        role: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Возвращает список активных (ONLINE) узлов с опциональной фильтрацией."""
        now = time.time()
        active: List[Dict[str, Any]] = []

        with self._lock:
            for node in self._nodes.values():
                # Проверка времени жизни пульса
                staleness = now - node["last_heartbeat"]
                if staleness > node["lease_ttl_seconds"] * 2:
                    node["status"] = "DEGRADED"

                if node["status"] != "ONLINE":
                    continue
                if role and node["role"] != role:
                    continue
                if capability and capability not in node["capabilities"]:
                    continue

                active.append(dict(node))

        return active

    def evict_stale_nodes(self, max_staleness_seconds: float = 60.0) -> List[str]:
        """Удаление узлов, не подававших пульс дольше max_staleness_seconds."""
        now = time.time()
        evicted: List[str] = []

        with self._lock:
            stale_keys = [
                nid for nid, node in self._nodes.items()
                if (now - node["last_heartbeat"]) > max_staleness_seconds
            ]
            for nid in stale_keys:
                del self._nodes[nid]
                evicted.append(nid)

        if evicted:
            logger.info("Evicted %d stale node(s) from cluster [%s]: %s", len(evicted), self.cluster_id, evicted)
        return evicted

    def get_cluster_topology(self) -> Dict[str, Any]:
        """Формирование агрегированного топологического среза кластера."""
        now = time.time()
        with self._lock:
            nodes_copy = [dict(n) for n in self._nodes.values()]

        role_counts: Dict[str, int] = {}
        for n in nodes_copy:
            role = n["role"]
            role_counts[role] = role_counts.get(role, 0) + 1

        return {
            "cluster_id": self.cluster_id,
            "total_nodes": len(nodes_copy),
            "online_nodes": len([n for n in nodes_copy if n["status"] == "ONLINE"]),
            "role_distribution": role_counts,
            "nodes": nodes_copy,
            "timestamp": now,
        }
