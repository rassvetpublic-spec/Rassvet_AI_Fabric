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

import ipaddress
import json
import logging
import math
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
        # Beacon is an untrusted discovery hint, not an authenticated origin.
        if not isinstance(raw, bytes) or not raw or len(raw) > 8192:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict) or data.get("protocol") != "BPR5_NEXTGEN_R3.3" or data.get("stage") != "STAGE_R29_LAN_P2P":
                return None
            if (not isinstance(data.get("node_id"), str) or
                    not 0 < len(data["node_id"]) <= 128 or
                    not isinstance(data.get("host"), str) or
                    not 0 < len(data["host"]) <= 255 or
                    type(data.get("port")) is not int or not 1 <= data["port"] <= 65535 or
                    not isinstance(data.get("merkle_root"), str) or
                    not 0 < len(data["merkle_root"]) <= 128 or
                    type(data.get("checkpoints_count")) is not int or data["checkpoints_count"] < 0 or
                    type(data.get("ttl_seconds")) not in (int, float) or
                    not math.isfinite(data["ttl_seconds"]) or
                    not 0 < data["ttl_seconds"] <= 300 or
                    type(data.get("timestamp")) not in (int, float) or
                    not math.isfinite(data["timestamp"]) or
                    data["timestamp"] <= 0 or
                    not isinstance(data.get("capabilities"), list) or
                    len(data["capabilities"]) > 32 or
                    not all(isinstance(c, str) and 0 < len(c) <= 128 for c in data["capabilities"])):
                return None
            return cls.from_dict(data)
        except (ValueError, TypeError, KeyError, UnicodeDecodeError, OverflowError) as exc:
            logger.debug("Failed to parse LanBeacon packet: %s", exc)
        return None


class PeerState:
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    SUSPECT = "SUSPECT"
    FAILED = "FAILED"


class EWMAPingTracker:
    """Адаптивный EWMA-трекер пинга и скользящее 3-тиковое окно отказоустойчивости (Stage R33 / R5)."""

    def __init__(
        self,
        alpha: float = 0.25,
        tick_interval_sec: float = 1.5,
        failover_ticks: int = 3,
        degraded_rtt_ms: float = 200.0,
    ) -> None:
        self.alpha = alpha
        self.tick_interval_sec = tick_interval_sec
        self.failover_ticks = failover_ticks
        self.max_failover_sec = tick_interval_sec * failover_ticks
        self.degraded_rtt_ms = degraded_rtt_ms
        self._peers: Dict[str, Dict[str, Any]] = {}

    def record_ping(self, peer_id: str, rtt_ms: float, timestamp: Optional[float] = None) -> float:
        """Регистрация замера RTT и обновление скользящего среднего EWMA."""
        ts = timestamp if timestamp is not None else time.time()
        if (not isinstance(peer_id, str) or not peer_id or
                type(rtt_ms) not in (int, float) or not math.isfinite(rtt_ms) or rtt_ms < 0 or
                type(ts) not in (int, float) or not math.isfinite(ts)):
            raise ValueError("Invalid peer RTT/timestamp telemetry")
        if peer_id not in self._peers:
            self._peers[peer_id] = {
                "rtt_ewma": float(rtt_ms),
                "last_seen_ts": ts,
                "pings_count": 1,
            }
            return float(rtt_ms)

        info = self._peers[peer_id]
        prev_ewma = info["rtt_ewma"]
        new_ewma = (self.alpha * rtt_ms) + ((1.0 - self.alpha) * prev_ewma)
        info["rtt_ewma"] = new_ewma
        info["last_seen_ts"] = ts
        info["pings_count"] += 1
        return new_ewma

    def get_state(self, peer_id: str, now: Optional[float] = None) -> str:
        """Определение состояния пира по формуле скользящего 3-тикового окна."""
        if peer_id not in self._peers:
            return PeerState.FAILED

        info = self._peers[peer_id]
        current_time = now if now is not None else time.time()
        elapsed = max(0.0, current_time - info["last_seen_ts"])

        if elapsed >= self.max_failover_sec:
            return PeerState.FAILED
        elif elapsed >= self.tick_interval_sec:
            return PeerState.SUSPECT
        elif info["rtt_ewma"] >= self.degraded_rtt_ms:
            return PeerState.DEGRADED
        return PeerState.ONLINE

    def get_peer_metrics(self, peer_id: str, now: Optional[float] = None) -> Dict[str, Any]:
        """Телеметрия RTT и состояния пира."""
        if peer_id not in self._peers:
            return {"peer_id": peer_id, "state": PeerState.FAILED, "rtt_ewma_ms": 0.0}
        info = self._peers[peer_id]
        current_time = now if now is not None else time.time()
        elapsed = max(0.0, current_time - info["last_seen_ts"])
        return {
            "peer_id": peer_id,
            "state": self.get_state(peer_id, now=current_time),
            "rtt_ewma_ms": round(info["rtt_ewma"], 2),
            "pings_count": info["pings_count"],
            "seconds_since_last_ping": round(elapsed, 2),
        }


class LanPeerDiscovery:
    """Реестр и координатор обнаружения пиров локальной сети с отслеживанием TTL."""

    def __init__(
        self,
        beacon_port: int = DEFAULT_BEACON_PORT,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        ping_tracker: Optional[EWMAPingTracker] = None,
    ) -> None:
        self.beacon_port = beacon_port
        self.ttl_seconds = ttl_seconds
        self.ping_tracker = ping_tracker or EWMAPingTracker()
        self.peers: Dict[str, Dict[str, Any]] = {}

    def register_peer(self, beacon: LanBeacon) -> bool:
        """Record an unverified discovery hint only while its lease and order are valid."""
        now = time.time()
        if (not isinstance(beacon, LanBeacon) or
                not isinstance(beacon.node_id, str) or not 0 < len(beacon.node_id) <= 128 or
                not isinstance(beacon.host, str) or not beacon.host.strip() or
                not 1 <= beacon.port <= 65535 or
                not isinstance(beacon.merkle_root, str) or not beacon.merkle_root or
                beacon.checkpoints_count < 0 or
                not math.isfinite(beacon.ttl_seconds) or not 0 < beacon.ttl_seconds <= 300 or
                not math.isfinite(beacon.timestamp) or
                beacon.timestamp + beacon.ttl_seconds <= now or
                beacon.timestamp > now + 5.0):
            return False
        prior = self.peers.get(beacon.node_id)
        if prior and beacon.timestamp <= prior.get("remote_timestamp", 0):
            return False
        self.ping_tracker.record_ping(beacon.node_id, rtt_ms=1.0, timestamp=now)
        self.peers[beacon.node_id] = {
            "node_id": beacon.node_id,
            "endpoint": f"http://{beacon.host}:{beacon.port}",
            "host": beacon.host,
            "port": beacon.port,
            "merkle_root": beacon.merkle_root,
            "checkpoints_count": beacon.checkpoints_count,
            "capabilities": beacon.capabilities,
            "last_seen_ts": now,
            "remote_timestamp": beacon.timestamp,
            "expires_at": now + beacon.ttl_seconds,
            "status": "ONLINE",
        }
        return True

    def register_synthetic_peer(self, peer_data: Dict[str, Any]) -> None:
        """Регистрация синтетического пира для детерминированного тестирования без сети."""
        node_id = peer_data.get("node_id", f"synthetic-{int(time.time())}")
        now = time.time()
        ttl = peer_data.get("ttl_seconds", self.ttl_seconds)
        rtt = peer_data.get("rtt_ms", 1.0)
        self.ping_tracker.record_ping(node_id, rtt_ms=rtt, timestamp=now)
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
        now = time.time()
        for nid, p in self.peers.items():
            st = self.ping_tracker.get_state(nid, now=now)
            p["status"] = st
            p["ewma_metrics"] = self.ping_tracker.get_peer_metrics(nid, now=now)
        return [dict(p) for p in self.peers.values()
                if p["status"] in (PeerState.ONLINE, PeerState.DEGRADED)]

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
        if beacon is None:
            return None
        now = time.time()
        if (beacon.timestamp + beacon.ttl_seconds <= now or
                beacon.timestamp > now + 5.0):
            return None
        try:
            source_ip = str(ipaddress.IPv4Address(sender_addr[0]))
            if not isinstance(sender_addr[1], int) or not 1 <= sender_addr[1] <= 65535:
                return None
        except (IndexError, ValueError, TypeError, ipaddress.AddressValueError):
            return None
        prior = self.peers.get(beacon.node_id)
        if prior and beacon.timestamp <= prior.get("remote_timestamp", 0):
            return None  # Replayed or older advertisement cannot roll back topology.
        # UDP sender address is an observed hint; advertised host is untrusted.
        # This does NOT authenticate the sender or authorize execution.
        beacon.host = source_ip
        return beacon if self.register_peer(beacon) else None


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
        safe_offer = peer_offer if isinstance(peer_offer, dict) else {}
        diff = self.exchange.compare_offers(local_offer, safe_offer)
        diff["peer_node_id"] = safe_offer.get("node_id", "unknown-peer")
        diff["invalid_offer"] = not isinstance(peer_offer, dict)
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
        if diff.get("invalid_offer"):
            return {
                "status": "DIVERGENT", "is_parity": False,
                "errors": ["INVALID_PEER_OFFER"], "reconciled_items": [],
                "origin_authenticated": False, "applied_to_local_store": False,
                "evidence_grade": "UNVERIFIED_REMOTE_OFFER", "diff": diff,
            }
        if diff["is_parity"]:
            return {
                "status": "IN_SYNC",  # backward-compatible, self-declared offer only
                "is_parity": True,
                "merkle_root": diff["local_root"],
                "reconciled_count": 0,
                "origin_authenticated": False,
                "applied_to_local_store": False,
                "evidence_grade": "SELF_DECLARED_OFFER_ONLY",
                "message": "Merkle root and manifest claims match; peer identity and file presence not attested",
                "diff": diff,
            }

        reconciled: List[str] = []
        errors: List[str] = []

        # This routine only validates in memory. Never imply that any remote
        # checkpoint has been written to the local canonical store.
        missing_in_local = diff.get("missing_in_local", [])
        if len(missing_in_local) > 2048:
            errors.append("UNBOUNDED_REMOTE_MANIFEST")
        elif fetch_checkpoint_fn and missing_in_local:
            remote_manifest = peer_offer.get("items_manifest", {})
            for cp_name in missing_in_local:
                # The callback may be backed by a filesystem: no path traversal,
                # subdirectories, drive prefixes or arbitrary remote file types.
                if (not isinstance(cp_name, str) or not 0 < len(cp_name) <= 255 or
                        cp_name in (".", "..") or "/" in cp_name or
                        "\\" in cp_name or ":" in cp_name or
                        not cp_name.endswith((".json", ".md"))):
                    errors.append("INVALID_PEER_CHECKPOINT_NAME")
                    continue
                expected_hash = remote_manifest.get(cp_name)
                if (not isinstance(expected_hash, str) or len(expected_hash) != 64 or
                        any(ch not in "0123456789abcdef" for ch in expected_hash)):
                    errors.append("INVALID_PEER_CHECKPOINT_HASH")
                    continue
                try:
                    payload = fetch_checkpoint_fn(cp_name)
                except Exception as exc:
                    errors.append(f"PEER_FETCH_FAILED:{type(exc).__name__}")
                    continue
                if not isinstance(payload, dict):
                    errors.append("INVALID_PEER_CHECKPOINT_PAYLOAD")
                    continue
                try:
                    raw = json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")
                except (TypeError, ValueError):
                    errors.append("INVALID_PEER_CHECKPOINT_JSON")
                    continue
                if len(raw) > 8 * 1024 * 1024:
                    errors.append("OVERSIZE_PEER_CHECKPOINT")
                    continue
                import hashlib
                if hashlib.sha256(raw).hexdigest() == expected_hash:
                    reconciled.append(cp_name)
                else:
                    errors.append("PEER_CHECKPOINT_HASH_MISMATCH")

        return {
            "status": ("RECONCILED" if (reconciled and not errors and
                                      not diff.get("divergent_files") and
                                      not diff.get("missing_in_remote")) else "DIVERGENT"),
            "is_parity": False,
            "local_root": diff["local_root"],
            "peer_root": diff["remote_root"],
            "missing_in_local_count": len(missing_in_local),
            "reconciled_items": reconciled,
            "errors": errors,
            "origin_authenticated": False,
            "applied_to_local_store": False,
            "evidence_grade": ("IN_MEMORY_HASH_MATCH_ONLY" if reconciled else
                               "UNVERIFIED_REMOTE_OFFER"),
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
                "is_synced": is_peer_synced,  # legacy: advertised root equality
                "origin_authenticated": False,
                "parity_evidence": "REMOTE_ROOT_HINT_ONLY",
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
            "remote_parity_authenticated": False,
            "local_merkle_root": local_root,
            "nodes": nodes_summary,
            "timestamp": time.time(),
        }
