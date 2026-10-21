"""Unit and adversarial tests for Horizon Improvements (Stage R34).

Covers:
- [A-X] AdaptiveChunkSizer (FastCDC 8 MB <-> 32 MB dynamic bounds based on bandwidth)
- [B-Y] NvcompZstdCompressorWrapper (GPU nvCOMP acceleration with CPU zstd/zlib fallback)
- [C-Z] ZkMmrCompressor & ZkReceiptProof (O(1) zk-SNARK verification for MMR historical checkpoints)
"""

import hashlib
import io
import os
import pytest

from rai_fabric.model_replicator import (
    AdaptiveChunkSizer,
    FastCDCChunker,
    NvcompZstdCompressorWrapper,
)
from rai_fabric.tri_tower_sync import (
    MerkleMountainRange,
    ZkMmrCompressor,
    ZkReceiptProof,
)


# ==============================================================================
# [A-X] Adaptive FastCDC Chunk Size Tests
# ==============================================================================

def test_adaptive_chunk_sizer_bandwidth_scaling():
    sizer = AdaptiveChunkSizer(default_bandwidth_mbps=100.0)

    # 1. 100 MB/s (1 Gbps LAN): bounds (2MB, 8MB, 16MB)
    min_sz, avg_sz, max_sz = sizer.determine_chunk_bounds()
    assert avg_sz == 8 * 1024 * 1024
    assert min_sz == 2 * 1024 * 1024
    assert max_sz == 16 * 1024 * 1024

    # 2. Record fast transfers (simulate 500 MB/s ~ 5 Gbps LAN)
    sizer.record_transfer(transferred_bytes=500 * 1024 * 1024, duration_sec=1.0)
    # Bandwidth will adjust up
    min_sz_mid, avg_sz_mid, max_sz_mid = sizer.determine_chunk_bounds(bandwidth_mbps=500.0)
    assert avg_sz_mid == 16 * 1024 * 1024
    assert min_sz_mid == 4 * 1024 * 1024
    assert max_sz_mid == 32 * 1024 * 1024

    # 3. 10 Gbps P2P / direct NVMe link (> 800 MB/s)
    min_sz_hi, avg_sz_hi, max_sz_hi = sizer.determine_chunk_bounds(bandwidth_mbps=1200.0)
    assert avg_sz_hi == 32 * 1024 * 1024
    assert min_sz_hi == 8 * 1024 * 1024
    assert max_sz_hi == 64 * 1024 * 1024


def test_fastcdc_adaptive_chunk_stream():
    chunker = FastCDCChunker()
    sizer = AdaptiveChunkSizer(default_bandwidth_mbps=50.0)

    # Synthetic stream 100 KB with custom bounds for quick test
    data = b"ADAPTIVE_FASTCDC_TEST_DATA_" * 4000
    stream = io.BytesIO(data)

    # Force smaller test bounds in sizer for fast in-memory execution
    sizer.determine_chunk_bounds = lambda: (512, 1024, 2048)  # type: ignore

    chunks = list(chunker.adaptive_chunk_stream(stream, sizer=sizer))
    assert len(chunks) > 1
    reconstructed = b"".join(c[0] for c in chunks)
    assert reconstructed == data


# ==============================================================================
# [B-Y] GPU nvCOMP Acceleration & Fallback Tests
# ==============================================================================

def test_nvcomp_compressor_mock_gpu_mode():
    wrapper = NvcompZstdCompressorWrapper(level=3, prefer_gpu=True)
    wrapper.enable_mock_gpu(True)
    assert wrapper.is_gpu_accelerated is True

    payload = b"\xAA\xBB\xCC\xDD" * 8192  # 32 KB
    compressed, backend = wrapper.compress_chunk(payload)

    assert backend == "NVCOMP_GPU"
    assert compressed.startswith(b"NVCP")

    decompressed = wrapper.decompress_chunk(compressed)
    assert decompressed == payload


def test_nvcomp_compressor_cpu_fallback():
    wrapper = NvcompZstdCompressorWrapper(level=3, prefer_gpu=False)
    assert wrapper.is_gpu_accelerated is False

    payload = b"SAMPLE_PAYLOAD_FOR_CPU_COMPRESSION" * 100
    compressed, backend = wrapper.compress_chunk(payload)

    assert backend in ("ZSTD_CPU", "ZLIB_CPU")
    assert not compressed.startswith(b"NVCP")

    decompressed = wrapper.decompress_chunk(compressed)
    assert decompressed == payload


# ==============================================================================
# [C-Z] zk-SNARK MMR Receipt Compression Tests
# ==============================================================================

def test_zk_mmr_receipt_generation_and_o1_verification():
    mmr = MerkleMountainRange()
    # Add 146 historical checkpoints
    checkpoints_count = 146
    for i in range(checkpoints_count):
        h = hashlib.sha256(f"HISTORICAL_CHECKPOINT_{i}".encode("utf-8")).hexdigest()
        mmr.append(h)

    root = mmr.get_root()

    # Generate constant-size O(1) zk-SNARK receipt proof
    zk_receipt = ZkMmrCompressor.generate_zk_receipt(
        mmr=mmr,
        checkpoints_count=checkpoints_count,
        circuit_epoch=1,
    )

    assert isinstance(zk_receipt, ZkReceiptProof)
    assert zk_receipt.proof_size_bytes == 192
    assert zk_receipt.merkle_root == root
    assert zk_receipt.checkpoints_count == checkpoints_count

    # Verification O(1) against expected root
    is_valid = ZkMmrCompressor.verify_zk_receipt(zk_receipt, expected_root=root)
    assert is_valid is True

    # Tampered root must fail verification
    bad_root = hashlib.sha256(b"tampered_root").hexdigest()
    assert ZkMmrCompressor.verify_zk_receipt(zk_receipt, expected_root=bad_root) is False

    # Tampered public input hash must fail verification
    zk_receipt_tampered = ZkReceiptProof(
        merkle_root=zk_receipt.merkle_root,
        checkpoints_count=zk_receipt.checkpoints_count,
        circuit_epoch=zk_receipt.circuit_epoch,
        proof_a=zk_receipt.proof_a,
        proof_b=zk_receipt.proof_b,
        proof_c=zk_receipt.proof_c,
        public_inputs_hash="tampered_hash",
        proof_size_bytes=192,
    )
    assert ZkMmrCompressor.verify_zk_receipt(zk_receipt_tampered, expected_root=root) is False
