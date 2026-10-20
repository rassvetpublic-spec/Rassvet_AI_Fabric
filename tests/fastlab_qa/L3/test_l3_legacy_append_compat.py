"""R10 cross-generation compatibility for manifest-free direct chunk append.

Compatibility is bounded, sequential and never a complete model attestation.
"""
import hashlib
import time
from rai_fabric.model_replicator import ModelReplicator
from rai_fabric.p2p_lan_sync import LanPeerDiscovery, LanBeacon


def test_legacy_direct_two_small_chunks_remain_appendable(tmp_path):
    r=ModelReplicator(tmp_path/"models")
    blocks=[b"small-A",b"small-B"]
    for i,b in enumerate(blocks):
        assert r.import_chunk_direct("toy", i, sum(map(len,blocks[:i])), b, hashlib.sha256(b).hexdigest()) is True
    assert r._get_model_path("toy").read_bytes()==b"".join(blocks)
    assert r.get_model_status("toy")["status"]=="PRESENT_UNVERIFIED"


def test_legacy_direct_disallows_sparse_and_rewrite(tmp_path):
    r=ModelReplicator(tmp_path/"models")
    b=b"payload"; digest=hashlib.sha256(b).hexdigest()
    assert r.import_chunk_direct("toy",0,0,b,digest)
    assert r.import_chunk_direct("toy",1,100,b,digest) is False
    assert r.import_chunk_direct("toy",0,0,b,digest) is False
    assert r.import_chunk_direct("other",0,2**26,b,digest) is False
    assert not r._get_model_path("other").exists()
    assert r._get_model_path("toy").read_bytes()==b


def test_lan_observed_peer_accepts_current_not_stale_beacon():
    d=LanPeerDiscovery()
    fresh=LanBeacon("m3-peer","10.0.0.5",11434,"root",1,timestamp=time.time())
    assert d.register_peer(fresh) is True
    stale=LanBeacon("old","10.0.0.5",11434,"root",1,timestamp=1000.0)
    assert d.register_peer(stale) is False
    assert len(d.get_active_peers())==1
