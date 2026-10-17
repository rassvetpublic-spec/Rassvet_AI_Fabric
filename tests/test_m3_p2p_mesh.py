"""Unit and adversarial tests for Milestone M3 (R4, R5): FastCDC & Adaptive P2P Mesh.

Covers:
- R4: FastCDCChunker (Gear Hash rolling window chunk boundary detection)
- R4: ZstdCompressorWrapper (Zstd/Zlib level 3 streaming chunk compression)
- R4: import_chunk_direct (Zero SSD Wear direct file offset writes)
- R5: EWMAPingTracker (EWMA smoothing, 3-tick sliding window failover, rapid state transitions)
- R5: LanPeerDiscovery EWMA integration
"""

import io
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from rai_fabric.model_replicator import (
    FastCDCChunker,
    ZstdCompressorWrapper,
    ModelReplicator,
    ModelManifest,
)
from rai_fabric.p2p_lan_sync import (
    EWMAPingTracker,
    PeerState,
    LanPeerDiscovery,
    LanBeacon,
)


# ==============================================================================
# R4: FastCDC & Zstandard Compression Tests
# ==============================================================================

def test_fastcdc_chunker_variable_boundaries():
    chunker = FastCDCChunker(min_size=256, avg_size=512, max_size=1024)
    # Generate 4 KB of synthetic repetitive and non-repetitive data
    data = (b"RASSVET_AI_FABRIC_CHUNK_" * 50) + (os.urandom(2048))
    stream = io.BytesIO(data)

    chunks = list(chunker.chunk_stream(stream, min_size=256, avg_size=512, max_size=1024))
    assert len(chunks) > 1

    total_reconstructed = b"".join(c[0] for c in chunks)
    assert total_reconstructed == data

    for chunk_bytes, chunk_hash in chunks:
        assert len(chunk_bytes) >= 256 or chunk_bytes == chunks[-1][0]
        assert len(chunk_bytes) <= 1024
        assert len(chunk_hash) == 64


def test_zstd_compressor_wrapper_roundtrip():
    wrapper = ZstdCompressorWrapper(level=3)
    # Highly compressible model weight sample
    raw_payload = b"\x00\x01\x00\x02" * 16384  # 64 KB

    compressed = wrapper.compress_chunk(raw_payload)
    # Bandwidth reduction: should be at least 40% smaller
    reduction_pct = (1.0 - (len(compressed) / len(raw_payload))) * 100
    assert reduction_pct >= 40.0

    restored = wrapper.decompress_chunk(compressed)
    assert restored == raw_payload


def test_model_replicator_import_chunk_direct(tmp_path):
    replicator = ModelReplicator(models_dir=tmp_path / "models")
    model_name = "direct-model-test"
    chunk_0 = b"PAGE_0000_DATA" * 64
    chunk_1 = b"PAGE_0001_DATA" * 64

    import hashlib
    h0 = hashlib.sha256(chunk_0).hexdigest()
    h1 = hashlib.sha256(chunk_1).hexdigest()

    # Direct import chunk 0 at offset 0
    ok0 = replicator.import_chunk_direct(model_name, 0, offset=0, chunk_data=chunk_0, expected_hash=h0)
    assert ok0 is True

    # Direct import chunk 1 at offset len(chunk_0)
    ok1 = replicator.import_chunk_direct(model_name, 1, offset=len(chunk_0), chunk_data=chunk_1, expected_hash=h1)
    assert ok1 is True

    # Check corrupted hash rejection (Fail-closed)
    ok_corrupted = replicator.import_chunk_direct(model_name, 2, offset=len(chunk_0)*2, chunk_data=chunk_0, expected_hash="bad_hash")
    assert ok_corrupted is False

    target_file = replicator._get_model_path(model_name)
    assert target_file.is_file()
    assert target_file.read_bytes() == chunk_0 + chunk_1


# ==============================================================================
# R5: Adaptive EWMA Heartbeat & 3-Tick Window Tests
# ==============================================================================

def test_ewma_ping_tracker_math_and_smoothing():
    tracker = EWMAPingTracker(alpha=0.25, tick_interval_sec=1.5, failover_ticks=3)
    peer_id = "node-alpha"

    # Ping 1: initial value
    ewma1 = tracker.record_ping(peer_id, rtt_ms=10.0, timestamp=100.0)
    assert ewma1 == 10.0

    # Ping 2: 0.25 * 50 + 0.75 * 10 = 12.5 + 7.5 = 20.0
    ewma2 = tracker.record_ping(peer_id, rtt_ms=50.0, timestamp=101.0)
    assert ewma2 == 20.0

    # Ping 3: 0.25 * 100 + 0.75 * 20 = 25.0 + 15.0 = 40.0
    ewma3 = tracker.record_ping(peer_id, rtt_ms=100.0, timestamp=102.0)
    assert ewma3 == 40.0


def test_ewma_ping_tracker_3tick_sliding_window_states():
    tracker = EWMAPingTracker(alpha=0.25, tick_interval_sec=1.5, failover_ticks=3, degraded_rtt_ms=150.0)
    peer_id = "node-beta"

    t0 = 1000.0
    tracker.record_ping(peer_id, rtt_ms=10.0, timestamp=t0)

    # Within 1 tick (< 1.5s): ONLINE
    assert tracker.get_state(peer_id, now=t0 + 0.5) == PeerState.ONLINE

    # Degraded state on high RTT (< 1.5s): DEGRADED
    tracker.record_ping(peer_id, rtt_ms=600.0, timestamp=t0 + 0.8)
    assert tracker.get_state(peer_id, now=t0 + 0.9) == PeerState.DEGRADED

    # Reset with fast ping
    tracker.record_ping(peer_id, rtt_ms=10.0, timestamp=t0 + 1.0)
    tracker._peers[peer_id]["rtt_ewma"] = 15.0  # normalize

    # Tick 1 passed without heartbeat (elapsed = 2.0s): SUSPECT
    assert tracker.get_state(peer_id, now=t0 + 3.0) == PeerState.SUSPECT

    # 3 ticks passed without heartbeat (elapsed = 4.6s >= 4.5s): FAILED
    assert tracker.get_state(peer_id, now=t0 + 5.6) == PeerState.FAILED


def test_lan_discovery_ewma_integration():
    discovery = LanPeerDiscovery(ttl_seconds=30.0)
    beacon = LanBeacon(
        node_id="peer-gamma",
        host="10.0.0.5",
        port=11434,
        merkle_root="abc",
        checkpoints_count=10,
        timestamp=1000.0,
    )
    discovery.register_peer(beacon)

    peers = discovery.get_active_peers()
    assert len(peers) == 1
    assert peers[0]["node_id"] == "peer-gamma"
    assert "ewma_metrics" in peers[0]
    assert peers[0]["status"] == PeerState.ONLINE
