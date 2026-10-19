"""L3 isolated Ollama response and GPU watchdog contract negatives; no live calls."""
from __future__ import annotations

import json

import pytest

from rai_fabric.local_gpu_transport import GpuThermalWatchdog, LocalGpuTransport
from transport.ipc_channel import TransportError, TransportMessageEnvelope, TransportStatus


def test_l3_watchdog_background_unknown_telemetry_denies():
    watcher = GpuThermalWatchdog()
    watcher.get_telemetry = lambda: {'available': False, 'temperature_c': None, 'free_vram_mb': None}
    safe, reason = watcher.check_safety(is_interactive=False)
    assert safe is False
    assert reason is not None and 'telemetry' in reason.lower()


@pytest.mark.parametrize('temp,free', [(float('nan'), 4096.0), (55.0, float('nan')), (None, 4096.0)])
def test_l3_watchdog_background_invalid_or_nan_telemetry_denies(temp, free):
    watcher = GpuThermalWatchdog()
    watcher.set_mock_telemetry(temp, free)
    safe, reason = watcher.check_safety(is_interactive=False)
    assert safe is False
    assert reason


def _offline_http_send(monkeypatch, response, *, http_status=200, gpu_present=False):
    class FakeResponse:
        status = http_status
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self, *_):
            return json.dumps(response).encode('utf-8')
    monkeypatch.setattr('rai_fabric.local_gpu_transport.detect_local_gpu',
                        lambda: {'available': gpu_present, 'name': 'synthetic', 'vram_mb': 16000})
    monkeypatch.setattr('rai_fabric.local_gpu_transport.urllib.request.urlopen',
                        lambda *_, **__: FakeResponse())
    watcher = GpuThermalWatchdog()
    watcher.set_mock_telemetry(55.0, 4096.0)
    transport = LocalGpuTransport(watchdog=watcher)
    transport._status = TransportStatus.CONNECTED
    env = TransportMessageEnvelope.create(payload_type='command',
                                          payload={'prompt': 'offline fixture', 'interactive': False})
    return transport, env


@pytest.mark.parametrize('bad_response', [
    {'error': 'model not found'},
    {'response': 'synthetic incomplete', 'done': False, 'model': 'qwen2.5-coder:7b'},
    {'response': 'from wrong model', 'done': True, 'model': 'wrong:provider'},
])
def test_l3_ollama_false_success_payloads_are_rejected(monkeypatch, bad_response):
    transport, env = _offline_http_send(monkeypatch, bad_response)
    with pytest.raises(TransportError):
        transport.send(env)
    assert transport.sent_count == 0
    assert transport.receive(timeout=0.001) is None


def test_l3_ollama_non_200_refuses_success(monkeypatch):
    payload = {'response': 'not okay', 'done': True, 'model': 'qwen2.5-coder:7b'}
    transport, env = _offline_http_send(monkeypatch, payload, http_status=503)
    with pytest.raises(TransportError):
        transport.send(env)
    assert transport.sent_count == 0


def test_l3_ollama_valid_reply_does_not_claim_gpu_just_for_gpu_presence(monkeypatch):
    payload = {'response': 'result', 'done': True, 'model': 'qwen2.5-coder:7b',
               'eval_count': 5, 'total_duration': 10000000}
    transport, env = _offline_http_send(monkeypatch, payload, gpu_present=True)
    assert transport.send(env) is True
    reply = transport.receive(timeout=0.01)
    assert reply is not None
    assert reply.payload['reply']['text'] == 'result'
    assert reply.payload['reply']['eval_count'] == 5
    assert reply.payload['reply']['gpu_accelerated'] is None
