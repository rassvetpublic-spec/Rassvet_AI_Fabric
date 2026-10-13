# -*- coding: utf-8 -*-
import pytest
from pathlib import Path
from rai_fabric.fleet_common import (
    canonical_json,
    sha256_text,
    sha256_digest,
    utc_now_iso,
    load_json,
    atomic_write_json,
    fleet_fail,
    first_line,
    unique_json_pairs,
    load_strict_json,
    safe_close,
)


def test_canonical_json_ordering():
    data = {"b": 2, "a": 1, "nested": {"z": 10, "y": 20}}
    res = canonical_json(data)
    assert res == '{"a":1,"b":2,"nested":{"y":20,"z":10}}'


def test_sha256_text_and_digest():
    text = "hello fleet"
    h1 = sha256_text(text)
    assert len(h1) == 64
    d1 = sha256_digest({"msg": "hello"})
    assert len(d1) == 64
    d2 = sha256_digest({"msg": "hello"})
    assert d1 == d2


def test_utc_now_iso_format():
    iso_str = utc_now_iso()
    assert "T" in iso_str
    assert "+" in iso_str or "Z" in iso_str or iso_str.endswith("+00:00")


def test_atomic_write_and_load_json(tmp_path):
    file_path = tmp_path / "test_file.json"
    data = {"status": "OK", "fleet_id": 42}
    
    atomic_write_json(file_path, data)
    assert file_path.exists()
    
    loaded = load_json(file_path)
    assert loaded == data
    
    non_existent = tmp_path / "missing.json"
    assert load_json(non_existent, default={"missing": True}) == {"missing": True}


def test_fleet_fail_raises_system_exit():
    with pytest.raises(SystemExit) as exc_info:
        fleet_fail("Fatal test condition", exit_code=42)
    assert exc_info.value.code == 42


def test_first_line():
    assert first_line("  First line \nSecond line\nThird") == "First line"
    assert first_line("\n\n   Actual first line \nNext") == "Actual first line"
    assert first_line("") == ""
    assert first_line(None) == ""


def test_unique_json_pairs_and_load_strict_json():
    # Valid JSON
    valid_raw = b'{"alpha": 1, "beta": 2}'
    res = load_strict_json(valid_raw)
    assert res == {"alpha": 1, "beta": 2}

    # Duplicate key rejection
    dup_raw = b'{"key": 1, "key": 2}'
    with pytest.raises(ValueError, match="Duplicate JSON key detected: 'key'"):
        load_strict_json(dup_raw)

    # Byte limit rejection
    with pytest.raises(ValueError, match="exceeds byte limit"):
        load_strict_json(valid_raw, limit=10)

    # Invalid non-dict rejection
    array_raw = b'[1, 2, 3]'
    with pytest.raises(ValueError, match="Expected JSON object"):
        load_strict_json(array_raw)


def test_safe_close():
    class DummyResource:
        def __init__(self):
            self.closed = False
        def close(self):
            self.closed = True

    r = DummyResource()
    safe_close(r)
    assert r.closed is True

    # Closing None or object without close() should not raise
    safe_close(None)
    safe_close("just a string")

    # Closing resource that raises exception
    class FaultyResource:
        def close(self):
            raise OSError("I/O error during close")

    safe_close(FaultyResource())
