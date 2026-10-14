# -*- coding: utf-8 -*-
"""
rai_fabric.p2p_lan_sync - Протокол кросс-хостовой P2P Merkle-синхронизации и автообнаружения узлов в LAN (Stage R29 / R0.9).

Реализует:
  1. Формирование и парсинг легковесных маяков узлов (LanBeacon);
  2. Обнаружение пиров в локальной сети через UDP Broadcast / Beacon с контролем TTL;
  3. Децентрализованную сверку Merkle-корней O(1) между несколькими хостами флота;
  4. Антиэнтропийную дельта-синхронизацию контрольных точек (Missing/Divergent Checkpoints);
  5. Соблюдение инварианта Safe Sync Gate (Zero SSD Wear, Offline-Safe, Fail-Closed).

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / RAiF R29 / Rassvet_AI_Fabric.
"""

from __future__ import annotations

__version__ = "1.0.0"

import json
import logging
import socket
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rai_fabric.fleet_common import get_repo_root
from rai_fabric.p2p_merkle import P2PMerkleExchange

logger = logging.getLogger("raif.p2p_lan_sync")

DEFAULT_BEACON_PORT = 42424
DEFAULT_TTL_SECONDS = 30.0


class LanBeacon:
    """Пакет маяка узла для широковещательного автообнаружения в локальной сети."""

    def __init__(
        self,
        node_id: str,
        host: str,
        port: int,
        merkle_root: str,
        checkpoints_count: int,
        capabilities: Optional[List[str]] = None,
        timestamp: Optional[float] = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.node_id = str(node_id)
        self.host = str(host)
        self.port = int(port)
        self.merkle_root = str(merkle_root)
        self.checkpoints_count = int(checkpoints_count)
        self.capabilities = list(capabilities or ["inference", "merkle-sync"])
        self.timestamp = float(timestamp or time.time())
        self.ttl_seconds = float(ttl_seconds)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol": "BPR5_NEXTGEN_R3.3",
            "stage": "STAGE_R29_LAN_P2P",
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "merkle_root": self.merkle_root,
            "checkpoints_count": self.checkpoints_count,
            "capabilities": self.capabilities,
            "timestamp": self.timestamp,
            "ttl_seconds": self.ttl_seconds,
        }

    def to_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LanBeacon:
        return cls(
            node_id=data.get("node_id", "unknown-node"),
            host=data.get("host", "127.0.0.1"),
            port=data.get("port", 11434),
            merkle_root=data.get("merkle_root", ""),
            checkpoints_count=data.get("checkpoints_count", 0),
            capabilities=data.get("capabilities", []),
            timestamp=data.get("timestamp", time.time()),
            ttl_seconds=data.get("ttl_seconds", DEFAULT_TTL_SECONDS),
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> Optional[LanBeacon]:
        try:
            data = json.loads(raw.decode("utf-8"))
            if data.get("stage") == "STAGE_R29_LAN_P2P" and "node_id" in data:
                return cls.from_dict(data)
        except Exception as exc:
            logger.debug("Failed to parse LanBeacon packet: %s", exc)
        return None


class LanPeerDiscovery:
    """Реестр и координатор обнаружения пиров локальной сети с отслеживанием TTL."""

    def __init__(
        self,
        beacon_port: int = DEFAULT_BEACON_PORT,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.beacon_port = beacon_port
        self.ttl_seconds = ttl_seconds
        self.peers: Dict[str, Dict[str, Any]] = {}

    def register_peer(self, beacon: LanBeacon) -> None:
        """Регистрация или обновление пира по полученному маяку."""
        now = time.time()
        self.peers[beacon.node_id] = {
            "node_id": beacon.node_id,
            "endpoint": f"http://{beacon.host}:{beacon.port}",
            "host": beacon.host,
            "port": beacon.port,
            "merkle_root": beacon.merkle_root,
            "checkpoints_count": beacon.checkpoints_count,
            "capabilities": beacon.capabilities,
            "last_seen_ts": now,
            "expires_at": now + beacon.ttl_seconds,
            "status": "ONLINE",
        }

    def register_synthetic_peer(self, peer_data: Dict[str, Any]) -> None:
        """Регистрация синтетического пира для детерминированного тестирования без сети."""
        node_id = peer_data.get("node_id", f"synthetic-{int(time.time())}")
        now = time.time()
        ttl = peer_data.get("ttl_seconds", self.ttl_seconds)
        self.peers[node_id] = {
            "node_id": node_id,
            "endpoint": peer_data.get("endpoint", f"http://{peer_data.get('host', '127.0.0.1')}:{peer_data.get('port', 11434)}"),
            "host": peer_data.get("host", "127.0.0.1"),
            "port": peer_data.get("port", 11434),
            "merkle_root": peer_data.get("merkle_root", ""),
            "checkpoints_count": peer_data.get("checkpoints_count", 0),
            "capabilities": peer_data.get("capabilities", ["inference", "merkle-sync"]),
            "last_seen_ts": now,
            "expires_at": now + ttl,
            "status": "ONLINE",
        }

    def purge_expired_peers(self) -> int:
        """Удаление устаревших записей пиров, превысивших TTL."""
        now = time.time()
        expired = [nid for nid, p in self.peers.items() if p.get("expires_at", 0) <= now]
        for nid in expired:
            del self.peers[nid]
        return len(expired)

    def get_active_peers(self) -> List[Dict[str, Any]]:
        """Получение списка актуальных незаэкспиренных пиров."""
        self.purge_expired_peers()
        return list(self.peers.values())

    def broadcast_beacon(
        self,
        beacon: LanBeacon,
        target_ip: str = "255.255.255.255",
    ) -> bool:
        """Отправка широковещательного UDP-пакета (безопасный fail-closed перехват ошибок)."""
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.5)
            packet = beacon.to_bytes()
            sock.sendto(packet, (target_ip, self.beacon_port))
            return True
        except Exception as exc:
            logger.debug("Broadcast failed (expected in sandboxed/offline environments): %s", exc)
            return False
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    def receive_beacon_packet(self, raw_bytes: bytes, sender_addr: Tuple[str, int]) -> Optional[LanBeacon]:
        """Обработка входящего пакета маяка."""
        beacon = LanBeacon.from_bytes(raw_bytes)
        if beacon:
            # Если хост был указан как 0.0.0.0 или пустой, подставляем адрес отправителя
            if beacon.host in ("0.0.0.0", "", "localhost"):
                beacon.host = sender_addr[0]
            self.register_peer(beacon)
        return beacon


class CrossHostP2PSyncManager:
    """Менеджер P2P-синхронизации между рабочими станциями флота по локальной сети."""

    def __init__(
        self,
        repo_root: Optional[Path | str] = None,
        node_id: str = "local-workstation-node",
    ) -> None:
        self.repo_root = Path(repo_root) if repo_root else get_repo_root()
        self.node_id = str(node_id)
        self.discovery = LanPeerDiscovery()
        self.exchange = P2PMerkleExchange(repo_root=self.repo_root)

    def create_local_beacon(
        self,
        host: str = "127.0.0.1",
        port: int = 11434,
    ) -> LanBeacon:
        """Формирование актуального маяка на основе локального Merkle-состояния."""
        offer = self.exchange.create_sync_offer(node_id=self.node_id)
        return LanBeacon(
            node_id=self.node_id,
            host=host,
            port=port,
            merkle_root=offer.get("merkle_root", ""),
            checkpoints_count=offer.get("checkpoints_count", 0),
            capabilities=["inference", "merkle-sync", "multi-model"],
        )

    def evaluate_peer_parity(self, peer_offer: Dict[str, Any]) -> Dict[str, Any]:
        """Сравнение локального оффера с оффером удалённого пира."""
        local_offer = self.exchange.create_sync_offer(node_id=self.node_id)
        diff = self.exchange.compare_offers(local_offer, peer_offer)
        diff["peer_node_id"] = peer_offer.get("node_id", "unknown-peer")
        return diff

    def reconcile_with_peer(
        self,
        peer_offer: Dict[str, Any],
        fetch_checkpoint_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """
        Антиэнтропийное разрешение дельты с пиром (Stage R29).
        Если корни совпадают — 100% паритет, передача данных не требуется.
        Если обнаружены расхождения — верифицирует отсутствующие чекпойнты.
        """
        diff = self.evaluate_peer_parity(peer_offer)

        if diff["is_parity"]:
            return {
                "status": "IN_SYNC",
                "is_parity": True,
                "merkle_root": diff["local_root"],
                "reconciled_count": 0,
                "message": f"Хост '{diff['peer_node_id']}' находится в полном криптографическом паритете",
                "diff": diff,
            }

        reconciled: List[str] = []
        errors: List[str] = []

        # Если передана функция получения чекпойнта от пира
        missing_in_local = diff.get("missing_in_local", [])
        if fetch_checkpoint_fn and missing_in_local:
            for cp_name in missing_in_local:
                payload = fetch_checkpoint_fn(cp_name)
                if not payload:
                    errors.append(f"Не удалось получить {cp_name} от пира")
                    continue
                # In-memory верификация хэша
                expected_hash = peer_offer.get("items_manifest", {}).get(cp_name)
                if expected_hash:
                    # Валидация детерминированного хеша
                    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
                    import hashlib
                    actual_hash = hashlib.sha256(raw).hexdigest()
                    if actual_hash == expected_hash:
                        reconciled.append(cp_name)
                    else:
                        errors.append(f"Хэш {cp_name} не совпал с заявленным пиром")

        return {
            "status": "RECONCILED" if reconciled and not errors else "DIVERGENT",
            "is_parity": False,
            "local_root": diff["local_root"],
            "peer_root": diff["remote_root"],
            "missing_in_local_count": len(missing_in_local),
            "reconciled_items": reconciled,
            "errors": errors,
            "diff": diff,
        }

    def get_fleet_lan_topology(self) -> Dict[str, Any]:
        """Сводная топология узлов флота в локальной сети с оценкой паритета."""
        local_offer = self.exchange.create_sync_offer(node_id=self.node_id)
        local_root = local_offer.get("merkle_root", "")
        peers = self.discovery.get_active_peers()

        nodes_summary = [
            {
                "node_id": self.node_id,
                "role": "PRIMARY_COORDINATOR",
                "merkle_root": local_root,
                "checkpoints_count": local_offer.get("checkpoints_count", 0),
                "is_self": True,
                "status": "ONLINE",
            }
        ]

        synced_count = 1
        for p in peers:
            is_peer_synced = (p.get("merkle_root") == local_root) and bool(local_root)
            if is_peer_synced:
                synced_count += 1
            nodes_summary.append({
                "node_id": p.get("node_id"),
                "endpoint": p.get("endpoint"),
                "merkle_root": p.get("merkle_root"),
                "checkpoints_count": p.get("checkpoints_count"),
                "is_self": False,
                "is_synced": is_peer_synced,
                "status": p.get("status", "ONLINE"),
            })

        total_nodes = len(nodes_summary)
        return {
            "protocol": "BPR5_NEXTGEN_R3.3",
            "stage": "STAGE_R29_LAN_P2P",
            "local_node_id": self.node_id,
            "total_nodes": total_nodes,
            "synced_nodes": synced_count,
            "network_parity_pct": round((synced_count / max(total_nodes, 1)) * 100, 1),
            "local_merkle_root": local_root,
            "nodes": nodes_summary,
            "timestamp": time.time(),
        }
