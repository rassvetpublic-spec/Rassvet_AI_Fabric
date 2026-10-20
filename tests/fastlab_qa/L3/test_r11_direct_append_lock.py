"""Deterministic fail-closed regression for concurrent legacy model append."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import threading
import pytest
from rai_fabric.model_replicator import ModelReplicator


@pytest.mark.parametrize("distinct_manager", [False, True])
def test_concurrent_legacy_same_offset_single_winner(tmp_path, monkeypatch, distinct_manager):
    import rai_fabric.model_replicator as module
    manager=ModelReplicator(tmp_path/'models')
    manager2=ModelReplicator(tmp_path/'models') if distinct_manager else manager
    paused=threading.Event()
    resume=threading.Event()
    real_fdopen=os.fdopen
    first_id={'value':None}

    class WrappedFile:
        def __init__(self,real):self.real=real
        def __enter__(self):self.real.__enter__();return self
        def __exit__(self,*args):return self.real.__exit__(*args)
        def fileno(self):return self.real.fileno()
        def seek(self,*args):
            if threading.get_ident()==first_id['value']:
                paused.set()
                if not resume.wait(4):raise TimeoutError('writer lock repro stalled')
            return self.real.seek(*args)
        def write(self,data):return self.real.write(data)
        def flush(self):return self.real.flush()

    monkeypatch.setattr(module.os,'fdopen',lambda fd,mode:WrappedFile(real_fdopen(fd,mode)))
    def write_first():
        first_id['value']=threading.get_ident()
        data=b'AAAA'
        return manager.import_chunk_direct('toy',0,0,data,hashlib.sha256(data).hexdigest())
    def write_second():
        data=b'BBBB'
        return manager2.import_chunk_direct('toy',0,0,data,hashlib.sha256(data).hexdigest())

    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(write_first)
        try:
            assert paused.wait(timeout=3)
            second=pool.submit(write_second)
            second_result=second.result(timeout=3)
        finally:
            resume.set()
        first_result=first.result(timeout=3)
    persisted=manager._get_model_path('toy').read_bytes()
    assert first_result is True and second_result is False, (
        f'stale simultaneous append ACK first={first_result} second={second_result}, bytes={persisted!r}'
    )
    assert persisted==b'AAAA'


def test_legacy_lockfile_symlink_does_not_escape_model_root(tmp_path):
    manager=ModelReplicator(tmp_path/'models')
    victim=tmp_path/'outside'
    victim.write_bytes(b'UNTOUCHED')
    link=manager._get_model_path('toy').with_name('toy.bin.append.lock')
    try:
        link.symlink_to(victim)
    except (OSError,NotImplementedError):
        pytest.skip('symlink unavailable')
    data=b'DATA'
    assert manager.import_chunk_direct('toy',0,0,data,hashlib.sha256(data).hexdigest()) is False
    assert victim.read_bytes()==b'UNTOUCHED'
    assert not manager._get_model_path('toy').exists()
