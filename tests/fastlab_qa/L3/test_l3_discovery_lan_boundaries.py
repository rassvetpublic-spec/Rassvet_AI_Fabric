"""L3 offline-only negatives for discovery observability and LAN source hints.
No network, real GPU, identity attestation, or production authority.
"""
import json
import math
import time

import pytest

from rai_fabric.node_discovery import NodeDiscoveryRegistry
from rai_fabric.p2p_lan_sync import (
    LanBeacon,
    LanPeerDiscovery,
    EWMAPingTracker,
    PeerState,
    CrossHostP2PSyncManager,
)


def _beacon(**overrides):
    d = {"node_id":"peer-one", "host":"192.168.10.5", "port":11434,
         "merkle_root":"source-declared-root", "checkpoints_count":1,
         "capabilities":["inference"], "timestamp":time.time(), "ttl_seconds":15.0}
    d.update(overrides)
    return LanBeacon(**d)


def test_registry_rejects_unknown_role_without_fallback_compute():
    r = NodeDiscoveryRegistry()
    assert r.register_node('node-1', role='ADMIN_NODE') is False
    assert r.get_node('node-1') is None


@pytest.mark.parametrize('lease', [float('nan'),float('inf'),-1,0,False])
def test_registry_rejects_invalid_lease_without_online_entry(lease):
    r = NodeDiscoveryRegistry()
    assert r.register_node('bad-lease', lease_ttl_seconds=lease) is False
    assert r.list_active_nodes() == []


def test_registry_mutation_isolation_for_nested_resources_and_lists():
    r = NodeDiscoveryRegistry()
    resources = {'nested': {'vram_mb': 8192}}
    caps = ['inference']
    assert r.register_node('safe-1', resources=resources, capabilities=caps)
    resources['nested']['vram_mb'] = 0
    caps.append('admin')
    observed = r.get_node('safe-1')
    assert observed['resources']['nested']['vram_mb'] == 8192
    assert observed['capabilities'] == ['inference']
    observed['resources']['nested']['vram_mb'] = -1
    r.list_active_nodes()[0]['resources']['nested']['vram_mb'] = -1
    r.get_cluster_topology()['nodes'][0]['resources']['nested']['vram_mb'] = -1
    assert r.get_node('safe-1')['resources']['nested']['vram_mb'] == 8192


def test_registry_discovery_missing_id_cannot_invent_gpu_identity(monkeypatch):
    import urllib.request
    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, *_): return json.dumps({'capabilities':['inference'], 'resources':{'vram_mb':16000}}).encode()
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *args,**kwargs: FakeResponse())
    r = NodeDiscoveryRegistry()
    assert r.discover_local_gpu_node() is None
    assert r.list_active_nodes() == []


@pytest.mark.parametrize('bad', [
    {'ttl_seconds': -1.0}, {'ttl_seconds': float('nan')},
    {'port': 0}, {'port': 65536}, {'capabilities':'inference'},
    {'checkpoints_count': -1}, {'node_id': ''},
])
def test_onwire_beacon_rejects_invalid_fields(bad):
    payload = _beacon().to_dict()
    payload.update(bad)
    assert LanBeacon.from_bytes(json.dumps(payload).encode()) is None


def test_onwire_beacon_rejects_oversized_packet():
    payload = _beacon().to_dict()
    payload['noise'] = 'x' * 10000
    assert LanBeacon.from_bytes(json.dumps(payload).encode()) is None


def test_lan_sender_address_wins_over_untrusted_beacon_host():
    d = LanPeerDiscovery()
    raw = _beacon(host='198.51.100.20').to_bytes()
    beacon = d.receive_beacon_packet(raw, ('192.168.10.44', 50000))
    assert beacon is not None
    assert beacon.host == '192.168.10.44'
    peers = d.get_active_peers()
    assert peers[0]['host'] == '192.168.10.44'
    assert peers[0]['endpoint'] == 'http://192.168.10.44:11434'


def test_expired_and_future_lan_beacons_do_not_register():
    d = LanPeerDiscovery()
    for when in (time.time()-120, time.time()+120):
        assert d.receive_beacon_packet(_beacon(timestamp=when).to_bytes(), ('192.168.10.44', 60000)) is None
    assert d.peers == {}


def test_lan_replay_cannot_revert_newer_observed_root():
    d = LanPeerDiscovery()
    newer = _beacon(timestamp=time.time(), merkle_root='new-root')
    older = _beacon(timestamp=newer.timestamp - 2, merkle_root='old-root')
    assert d.receive_beacon_packet(newer.to_bytes(), ('192.168.10.5', 50000)) is not None
    assert d.receive_beacon_packet(older.to_bytes(), ('192.168.10.5', 50000)) is None
    assert d.get_active_peers()[0]['merkle_root'] == 'new-root'


@pytest.mark.parametrize('rtt', [float('nan'), float('inf'), -1.0])
def test_nan_or_negative_rtt_never_evaluates_as_healthy(rtt):
    tracker = EWMAPingTracker()
    with pytest.raises(ValueError):
        tracker.record_ping('fake-node', rtt)
    assert tracker.get_state('fake-node') == PeerState.FAILED


def test_expired_ping_tracker_state_not_counted_as_synced_fleet_peer(tmp_path):
    m = CrossHostP2PSyncManager(repo_root=tmp_path, node_id='local')
    local_root = m.exchange.create_sync_offer()['merkle_root']
    m.discovery.register_synthetic_peer({'node_id':'ghost','merkle_root':local_root,'ttl_seconds':1000})
    m.discovery.ping_tracker._peers['ghost']['last_seen_ts'] -= 1000
    topology = m.get_fleet_lan_topology()
    assert topology['synced_nodes'] == 1
    assert topology['total_nodes'] == 1


def test_invalid_heartbeat_does_not_update_lease_or_status():
    r = NodeDiscoveryRegistry()
    assert r.register_node('n')
    before = r.get_node('n')['last_heartbeat']
    assert r.heartbeat('n', resources=['not-a-dict']) is False
    assert r.get_node('n')['last_heartbeat'] == before


def test_stale_heartbeat_requires_explicit_registration():
    r = NodeDiscoveryRegistry()
    assert r.register_node('n', lease_ttl_seconds=0.01)
    with r._lock:
        r._nodes['n']['last_heartbeat'] -= 10.0
    assert r.heartbeat('n', resources={'temp': 10}) is False
    assert r.get_node('n')['status'] == 'DEGRADED'


def test_direct_invalid_beacon_does_not_poison_peer_registry():
    d = LanPeerDiscovery()
    assert d.register_peer(_beacon(ttl_seconds=float('nan'))) is False
    assert not d.peers


def test_direct_replayed_beacon_does_not_roll_back_peer_state():
    d = LanPeerDiscovery()
    ts = time.time()
    assert d.register_peer(_beacon(timestamp=ts, merkle_root='fresh')) is True
    assert d.register_peer(_beacon(timestamp=ts-1, merkle_root='stale')) is False
    assert d.get_active_peers()[0]['merkle_root'] == 'fresh'
