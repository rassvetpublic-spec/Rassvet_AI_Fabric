"""L3 standalone negative NVMe cache regressions; no GPU or external processes."""
from __future__ import annotations

import time

import pytest

from rai_fabric.nvme_kv_cache import NvmeKVCacheManager


def test_async_write_failure_is_acknowledged_and_not_reported_as_cache_hit(tmp_path, monkeypatch):
    cache = NvmeKVCacheManager(tmp_path / 'cache')
    def explode(*_args, **_kwargs):
        raise OSError('synthetic IO failure')
    monkeypatch.setattr(cache, '_write_entry', explode)
    assert cache.put('model', 'prefix', {'x': 1}, wait=False) is True
    for _ in range(100):
        if cache._staging_queue.qsize() == 0:
            break
        time.sleep(0.01)
    assert cache._staging_queue.qsize() == 0
    assert cache._staging_queue.unfinished_tasks == 0
    assert cache.get('model', 'prefix') is None
    cache.close()


def test_oversized_cache_entry_does_not_exceed_budget(tmp_path):
    cache = NvmeKVCacheManager(tmp_path / 'cache', max_bytes=512, block_size=4096)
    assert cache.put('model', 'pfx', {'x': 1}) is False
    assert cache.get_metrics()['current_bytes'] == 0
    assert list((tmp_path / 'cache').glob('*.raifcache')) == []
    cache.close()


def test_replacing_cache_entry_does_not_evict_other_key(tmp_path):
    cache = NvmeKVCacheManager(tmp_path / 'cache', max_bytes=8192, block_size=4096)
    assert cache.put('model', 'A', {'value': 1})
    assert cache.put('model', 'B', {'value': 2})
    assert cache.put('model', 'A', {'value': 3})
    assert cache.get('model', 'A') == {'value': 3}
    assert cache.get('model', 'B') == {'value': 2}
    assert cache.get_metrics()['current_bytes'] <= 8192
    cache.close()


def test_tmp_symlink_cannot_overwrite_file_outside_cache(tmp_path):
    cache = NvmeKVCacheManager(tmp_path / 'cache')
    key = cache.compute_key('model', 'prefix')
    target = cache.cache_dir / f'{key}.tmp'
    external = tmp_path / 'external'
    external.write_bytes(b'UNTOUCHED')
    try:
        target.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip('symlink unavailable')
    assert cache.put('model', 'prefix', {'x': 1}) is False
    assert external.read_bytes() == b'UNTOUCHED'
    cache.close()


def test_corrupted_cache_block_releases_capacity_accounting(tmp_path):
    from rai_fabric.nvme_kv_cache import HEADER_SIZE
    cache = NvmeKVCacheManager(tmp_path / 'cache', max_bytes=4096, block_size=4096)
    assert cache.put('model', 'prefix', {'k': 123})
    assert cache.get_metrics()['current_bytes'] == 4096
    key = cache.compute_key('model', 'prefix')
    path = cache.cache_dir / f'{key}.raifcache'
    with path.open('r+b') as f:
        f.seek(HEADER_SIZE + 1)
        data = f.read(1)
        f.seek(HEADER_SIZE + 1)
        f.write(bytes([data[0] ^ 0xff]))
    assert cache.get('model', 'prefix') is None
    assert cache.get_metrics()['current_bytes'] == 0
    cache.close()


def test_recover_rejects_unbounded_header_length_and_wrong_key_filename(tmp_path):
    import struct, hashlib
    from rai_fabric.nvme_kv_cache import MAGIC_HEADER, FORMAT_VERSION, HEADER_STRUCT
    root = tmp_path / 'cache'
    root.mkdir()
    bogus = root / (hashlib.sha256(b'entry').hexdigest() + '.raifcache')
    header = HEADER_STRUCT.pack(MAGIC_HEADER, FORMAT_VERSION, bytes(32), 0xffffffff, 0, time.time())
    bogus.write_bytes(header + b'\0' * (4096 - len(header)))
    cache = NvmeKVCacheManager(root)
    assert cache.get_metrics()['entries_count'] == 0
    assert not bogus.exists()
    cache.close()


def test_close_drains_queued_async_cache_entries(tmp_path):
    root = tmp_path / 'cache'
    cache = NvmeKVCacheManager(root)
    for i in range(12):
        assert cache.put('model', 'prefix-'+str(i), {'value': i}, wait=False)
    cache.close()
    with NvmeKVCacheManager(root) as reread:
        for i in range(12):
            assert reread.get('model', 'prefix-'+str(i)) == {'value': i}
