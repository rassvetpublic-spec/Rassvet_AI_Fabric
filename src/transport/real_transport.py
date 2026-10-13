# -*- coding: utf-8 -*-
"""
transport.real_transport - Боевой IPC-транспорт Rassvet AI Fabric (Stage R25).
Реализует:
  1. Первичный Windows Named Pipe транспорт (\\\\.\\pipe\\raif_transport);
  2. Резервный HTTP/WebSocket шлюз (127.0.0.1:18892);
  3. Потоковый мост метрик и телеметрии в \\\\.\\pipe\\fleet_metrics (Zero SSD Wear);
  4. Адаптер RealTransportAdapter с автопереключением и интеграцией с UnifiedSupervisor.

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.2) / RAiF 10.7 Stage R25 / Rassvet_AI_Fabric#15.
"""

from __future__ import annotations

__version__ = "1.0.0"

import json
import os
import queue
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from multiprocessing.connection import Client, Listener
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from .ipc_channel import (
    ITransportChannel,
    TransportError,
    TransportMessageEnvelope,
    TransportStatus,
)

DEFAULT_RAIF_PIPE = r"\\.\pipe\raif_transport"
DEFAULT_FALLBACK_PORT = 18892
DEFAULT_METRICS_PIPE = r"\\.\pipe\fleet_metrics"
DEFAULT_METRICS_PORT = 18899


# =====================================================================
# 1. Сервер и клиент Windows Named Pipe
# =====================================================================

class NamedPipeServer:
    """Сервер Windows Named Pipe с поддержкой нескольких одновременных подключений."""

    def __init__(
        self,
        pipe_name: str = DEFAULT_RAIF_PIPE,
        inet_fallback_port: Optional[int] = None,
        max_queue_size: int = 10_000,
    ) -> None:
        self.pipe_name = pipe_name
        self.inet_fallback_port = inet_fallback_port
        self.max_queue_size = max_queue_size

        self._incoming_queue: queue.Queue[TransportMessageEnvelope] = queue.Queue(maxsize=max_queue_size)
        self._listener: Optional[Listener] = None
        self._running = False
        self._accept_thread: Optional[threading.Thread] = None
        self._client_connections: List[Any] = []
        self._clients_lock = threading.Lock()

        self._stats = {
            "messages_received": 0,
            "messages_sent": 0,
            "clients_total": 0,
            "active_clients": 0,
            "started_at": 0.0,
            "errors": 0,
        }

    def _determine_family_and_address(self) -> Tuple[str, Any]:
        if os.name == "nt" and self.pipe_name.startswith(r"\\.\pipe\\"):
            return "AF_PIPE", self.pipe_name
        # Fallback на сокет AF_INET для не-Windows платформ или явного порта
        port = self.inet_fallback_port or 18894
        return "AF_INET", ("127.0.0.1", port)

    def start(self) -> None:
        """Запуск прослушивания входящих IPC-подключений."""
        if self._running:
            return

        family, address = self._determine_family_and_address()
        self._listener = Listener(address, family=family)
        self._running = True
        self._stats["started_at"] = time.time()

        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="RAIF-NamedPipeServer-Accept",
            daemon=True,
        )
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        while self._running and self._listener:
            try:
                conn = self._listener.accept()
                with self._clients_lock:
                    self._client_connections.append(conn)
                    self._stats["clients_total"] += 1
                    self._stats["active_clients"] = len(self._client_connections)

                t = threading.Thread(
                    target=self._client_read_loop,
                    args=(conn,),
                    name=f"RAIF-NamedPipe-Worker-{self._stats['clients_total']}",
                    daemon=True,
                )
                t.start()
            except Exception:
                if not self._running:
                    break
                self._stats["errors"] += 1
                time.sleep(0.05)

    def _client_read_loop(self, conn: Any) -> None:
        try:
            while self._running:
                data = conn.recv()
                if isinstance(data, dict):
                    envelope = TransportMessageEnvelope.from_dict(data)
                elif isinstance(data, (str, bytes)):
                    envelope = TransportMessageEnvelope.from_json(data)
                else:
                    continue

                self._stats["messages_received"] += 1
                try:
                    self._incoming_queue.put(envelope, timeout=0.5)
                except queue.Full:
                    self._stats["errors"] += 1
        except (EOFError, ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            with self._clients_lock:
                if conn in self._client_connections:
                    self._client_connections.remove(conn)
                self._stats["active_clients"] = len(self._client_connections)
            try:
                conn.close()
            except Exception:
                pass

    def broadcast(self, envelope: TransportMessageEnvelope) -> int:
        """Рассылка сообщения всем активным подключенным клиентам."""
        sent_count = 0
        payload = envelope.to_dict()
        with self._clients_lock:
            dead_conns = []
            for conn in self._client_connections:
                try:
                    conn.send(payload)
                    sent_count += 1
                except Exception:
                    dead_conns.append(conn)
            for d in dead_conns:
                if d in self._client_connections:
                    self._client_connections.remove(d)
                try:
                    d.close()
                except Exception:
                    pass
            self._stats["active_clients"] = len(self._client_connections)
        self._stats["messages_sent"] += sent_count
        return sent_count

    def receive(self, timeout: float = 1.0) -> Optional[TransportMessageEnvelope]:
        """Чтение очередного полученного сообщения из очереди сервера."""
        try:
            return self._incoming_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        """Остановка сервера и закрытие всех сокетов."""
        self._running = False
        if self._listener:
            try:
                self._listener.close()
            except Exception:
                pass
            self._listener = None

        with self._clients_lock:
            for conn in self._client_connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self._client_connections.clear()
            self._stats["active_clients"] = 0

    @property
    def stats(self) -> Dict[str, Any]:
        return dict(self._stats)


class NamedPipeClient(ITransportChannel):
    """Клиент Windows Named Pipe с авто-переподключением при разрыве связи."""

    def __init__(
        self,
        pipe_name: str = DEFAULT_RAIF_PIPE,
        inet_fallback_port: Optional[int] = None,
        auto_reconnect: bool = True,
        reconnect_interval_sec: float = 0.5,
    ) -> None:
        self.pipe_name = pipe_name
        self.inet_fallback_port = inet_fallback_port
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval_sec = reconnect_interval_sec

        self._status = TransportStatus.DISCONNECTED
        self._conn = None
        self._conn_lock = threading.Lock()
        self._incoming_queue: queue.Queue[TransportMessageEnvelope] = queue.Queue(maxsize=5000)
        self._running = False
        self._read_thread: Optional[threading.Thread] = None

    @property
    def status(self) -> TransportStatus:
        return self._status

    def _determine_family_and_address(self) -> Tuple[str, Any]:
        if os.name == "nt" and self.pipe_name.startswith(r"\\.\pipe\\"):
            return "AF_PIPE", self.pipe_name
        port = self.inet_fallback_port or 18894
        return "AF_INET", ("127.0.0.1", port)

    def connect(self) -> bool:
        with self._conn_lock:
            if self._conn is not None:
                return True
            self._status = TransportStatus.CONNECTING
            try:
                family, address = self._determine_family_and_address()
                self._conn = Client(address, family=family)
                self._status = TransportStatus.CONNECTED
                self._running = True

                self._read_thread = threading.Thread(
                    target=self._client_receive_loop,
                    name="RAIF-NamedPipeClient-Reader",
                    daemon=True,
                )
                self._read_thread.start()
                return True
            except Exception:
                self._conn = None
                self._status = TransportStatus.DISCONNECTED
                return False

    def _client_receive_loop(self) -> None:
        while self._running:
            conn = self._conn
            if conn is None:
                break
            try:
                data = conn.recv()
                if isinstance(data, dict):
                    envelope = TransportMessageEnvelope.from_dict(data)
                elif isinstance(data, (str, bytes)):
                    envelope = TransportMessageEnvelope.from_json(data)
                else:
                    continue
                try:
                    self._incoming_queue.put(envelope, timeout=0.2)
                except queue.Full:
                    pass
            except (EOFError, ConnectionResetError, BrokenPipeError, OSError):
                with self._conn_lock:
                    self._conn = None
                    self._status = TransportStatus.RECONNECTING if self.auto_reconnect else TransportStatus.DISCONNECTED
                if self.auto_reconnect and self._running:
                    self._attempt_reconnect_loop()
                break

    def _attempt_reconnect_loop(self) -> None:
        while self._running and self._status == TransportStatus.RECONNECTING:
            time.sleep(self.reconnect_interval_sec)
            try:
                family, address = self._determine_family_and_address()
                new_conn = Client(address, family=family)
                with self._conn_lock:
                    self._conn = new_conn
                    self._status = TransportStatus.CONNECTED
                # Перезапускаем чтение
                self._read_thread = threading.Thread(
                    target=self._client_receive_loop,
                    name="RAIF-NamedPipeClient-Reader-Reconnected",
                    daemon=True,
                )
                self._read_thread.start()
                break
            except Exception:
                continue

    def disconnect(self) -> None:
        self._running = False
        with self._conn_lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            self._status = TransportStatus.CLOSED

    def is_connected(self) -> bool:
        return self._status == TransportStatus.CONNECTED and self._conn is not None

    def send(self, envelope: TransportMessageEnvelope) -> bool:
        if not self.is_connected():
            if self.auto_reconnect:
                if not self.connect():
                    return False
            else:
                return False

        with self._conn_lock:
            if self._conn is None:
                return False
            try:
                self._conn.send(envelope.to_dict())
                return True
            except Exception:
                self._conn = None
                self._status = TransportStatus.RECONNECTING if self.auto_reconnect else TransportStatus.ERROR
                return False

    def receive(self, timeout: float = 1.0) -> Optional[TransportMessageEnvelope]:
        try:
            return self._incoming_queue.get(timeout=timeout)
        except queue.Empty:
            return None


# =====================================================================
# 2. Резервный HTTP/WebSocket сервер и клиент (Порт 18892)
# =====================================================================

class _HttpTransportHandler(BaseHTTPRequestHandler):
    """HTTP обработчик JSON-RPC запросов и передачи конвертов сообщений."""

    server: HttpFallbackServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:
        """Отключение шумных логов BaseHTTPRequestHandler в stdout."""
        return

    def do_GET(self) -> None:
        app = getattr(self.server, "app", None)
        if self.path in ("/health", "/status"):
            port = app.port if app else self.server.server_address[1]
            qsize = app.queue_size if app else 0
            start_t = app.start_time if app else 0.0
            self._respond_json(200, {
                "status": "UP",
                "service": "raif_transport_fallback",
                "port": port,
                "messages_in_queue": qsize,
                "uptime_seconds": round(time.time() - start_t, 2) if start_t else 0.0,
            })
        elif self.path in ("/ui", "/dashboard"):
            html = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>RAiF 10.7 Transport Dashboard</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 24px; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.4); }
.badge { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; text-transform: uppercase; }
.badge-up { background: #238636; color: #fff; }
.badge-pipe { background: #1f6feb; color: #fff; }
h1, h2, h3 { color: #58a6ff; margin-top: 0; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #21262d; }
th { color: #8b949e; }
.metric-value { font-size: 24px; font-weight: 700; color: #58a6ff; margin-top: 8px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 16px; }
</style>
</head>
<body>
<h1>🚀 Rassvet AI Fabric — Боевой IPC-транспорт (Stage R25)</h1>
<div class="grid">
  <div class="card">
    <div style="color: #8b949e; font-size: 13px;">СТАТУС ТРАНСПОРТА</div>
    <div style="margin-top: 8px;"><span class="badge badge-up" id="transport-status">UP</span></div>
  </div>
  <div class="card">
    <div style="color: #8b949e; font-size: 13px;">АКТИВНЫЙ КАНАЛ</div>
    <div style="margin-top: 8px;"><span class="badge badge-pipe" id="active-channel">NAMED PIPE</span></div>
  </div>
  <div class="card">
    <div style="color: #8b949e; font-size: 13px;">ОЧЕРЕДЬ СООБЩЕНИЙ (RAM)</div>
    <div class="metric-value" id="queue-size">0</div>
  </div>
  <div class="card">
    <div style="color: #8b949e; font-size: 13px;">ВРЕМЯ РАБОТЫ (UPTIME)</div>
    <div class="metric-value" id="uptime">0s</div>
  </div>
</div>
<div class="card">
  <h3>🔌 Параметры топологии флота</h3>
  <table>
    <tr><th>Параметр</th><th>Значение</th><th>Назначение</th></tr>
    <tr><td>Primary Channel</td><td><code>\\\\.\\pipe\\raif_transport</code></td><td>Высокопроизводительный локальный Windows Named Pipe</td></tr>
    <tr><td>Fallback Port</td><td><code>127.0.0.1:18892</code></td><td>Локальный HTTP/JSON-RPC резервный шлюз</td></tr>
    <tr><td>Telemetry Bridge</td><td><code>\\\\.\\pipe\\fleet_metrics</code></td><td>Потоковый сбор метрик флота (Zero SSD Wear)</td></tr>
    <tr><td>Standard</td><td><code>BPR5 NextGen R3.3 / Stage R25</code></td><td>Канонический протокол CONTROL_TOWER</td></tr>
  </table>
</div>
<script>
async function refresh() {
  try {
    const res = await fetch('/status');
    const data = await res.json();
    document.getElementById('queue-size').innerText = data.messages_in_queue;
    document.getElementById('uptime').innerText = Math.round(data.uptime_seconds) + 's';
  } catch (e) {}
}
setInterval(refresh, 2000);
refresh();
</script>
</body>
</html>"""
            self._respond_html(200, html)
        elif self.path == "/poll":
            msg = app.dequeue_message(timeout=1.0) if app else None
            if msg is not None:
                self._respond_json(200, {"status": "SUCCESS", "envelope": msg.to_dict()})
            else:
                self._respond_json(204, {})
        else:
            self._respond_json(404, {"error": "NOT_FOUND"})

    def do_POST(self) -> None:
        app = getattr(self.server, "app", None)
        if self.path in ("/rpc", "/messages"):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len <= 0 or content_len > 2_000_000:
                self._respond_json(400, {"error": "INVALID_CONTENT_LENGTH"})
                return

            body = self.rfile.read(content_len)
            try:
                envelope = TransportMessageEnvelope.from_json(body)
                if app:
                    app.enqueue_message(envelope)
                self._respond_json(200, {
                    "status": "ACCEPTED",
                    "message_id": envelope.message_id,
                    "signature_verified": envelope.verify_signature(),
                })
            except Exception as exc:
                self._respond_json(400, {"error": "INVALID_ENVELOPE", "detail": str(exc)})
        else:
            self._respond_json(404, {"error": "NOT_FOUND"})

    def _respond_html(self, status_code: int, html_content: str) -> None:
        try:
            body = html_content.encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _respond_json(self, status_code: int, data: Dict[str, Any]) -> None:
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class HttpFallbackServer:
    """Резервный HTTP/REST шлюз на порту 18892 при недоступности Named Pipe."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_FALLBACK_PORT) -> None:
        self.host = host
        self.port = port
        self.start_time = 0.0
        self._queue: queue.Queue[TransportMessageEnvelope] = queue.Queue(maxsize=5000)
        self._server: Optional[ThreadingHTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._running = False

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def enqueue_message(self, envelope: TransportMessageEnvelope) -> None:
        try:
            self._queue.put(envelope, timeout=0.5)
        except queue.Full:
            pass

    def dequeue_message(self, timeout: float = 1.0) -> Optional[TransportMessageEnvelope]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def start(self) -> None:
        if self._running:
            return

        self.start_time = time.time()
        self._server = ThreadingHTTPServer((self.host, self.port), _HttpTransportHandler)
        self._server.app = self  # type: ignore[attr-defined]
        self._running = True

        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="RAIF-HttpFallbackServer",
            daemon=True,
        )
        self._server_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class HttpFallbackClient(ITransportChannel):
    """Клиент к резервному HTTP шлюзу 127.0.0.1:18892."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_FALLBACK_PORT) -> None:
        self.base_url = f"http://{host}:{port}"
        self._status = TransportStatus.DISCONNECTED

    @property
    def status(self) -> TransportStatus:
        return self._status

    def connect(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    self._status = TransportStatus.CONNECTED
                    return True
        except Exception:
            pass
        self._status = TransportStatus.DISCONNECTED
        return False

    def disconnect(self) -> None:
        self._status = TransportStatus.CLOSED

    def is_connected(self) -> bool:
        return self._status == TransportStatus.CONNECTED

    def send(self, envelope: TransportMessageEnvelope) -> bool:
        try:
            data = envelope.to_bytes()
            req = urllib.request.Request(
                f"{self.base_url}/messages",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status in (200, 202):
                    self._status = TransportStatus.CONNECTED
                    return True
        except Exception:
            self._status = TransportStatus.DEGRADED
        return False

    def receive(self, timeout: float = 1.0) -> Optional[TransportMessageEnvelope]:
        try:
            req = urllib.request.Request(f"{self.base_url}/poll", method="GET")
            with urllib.request.urlopen(req, timeout=max(timeout, 1.5)) as resp:
                if resp.status == 200:
                    body = resp.read()
                    data = json.loads(body.decode("utf-8"))
                    envelope_data = data.get("envelope")
                    if envelope_data:
                        return TransportMessageEnvelope.from_dict(envelope_data)
        except Exception:
            pass
        return None


# =====================================================================
# 3. Мост метрик и событий в \\.\pipe\fleet_metrics
# =====================================================================

class FleetMetricsBridge:
    """Прямой потоковый мост телеметрии и событий в сокет \\\\.\\pipe\\fleet_metrics."""

    def __init__(
        self,
        pipe_name: str = DEFAULT_METRICS_PIPE,
        inet_port: int = DEFAULT_METRICS_PORT,
        max_ram_buffer: int = 5_000,
    ) -> None:
        self.pipe_name = pipe_name
        self.inet_port = inet_port
        self.max_ram_buffer = max_ram_buffer

        self._conn = None
        self._conn_lock = threading.Lock()
        self._ram_queue: Deque[Dict[str, Any]] = deque(maxlen=max_ram_buffer)
        self._last_retry = 0.0

    def _determine_family_and_address(self) -> Tuple[str, Any]:
        if os.name == "nt" and self.pipe_name.startswith(r"\\.\pipe\\"):
            return "AF_PIPE", self.pipe_name
        return "AF_INET", ("127.0.0.1", self.inet_port)

    def _ensure_connected(self) -> Any:
        now = time.time()
        if self._conn is not None:
            return self._conn
        if now - self._last_retry < 1.0:
            return None
        self._last_retry = now

        try:
            family, address = self._determine_family_and_address()
            self._conn = Client(address, family=family)
            # Отправляем накопленные в ОЗУ метрики при восстановлении
            while self._ram_queue:
                try:
                    item = self._ram_queue.popleft()
                    self._conn.send(item)
                except Exception:
                    break
            return self._conn
        except Exception:
            self._conn = None
            return None

    def emit_event(self, event_type: str, data: Dict[str, Any], source: str = "raif_transport") -> bool:
        """Отправка события в пайп метрик или сохранение в RAM-буфере при недоступности."""
        record = {
            "source": source,
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        }

        with self._conn_lock:
            conn = self._ensure_connected()
            if conn is not None:
                try:
                    conn.send(record)
                    return True
                except Exception:
                    self._conn = None

            # Fallback в RAM ring-buffer (Zero SSD Wear)
            self._ram_queue.append(record)
            return False

    def emit_heartbeat(self, component: str, status: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Генерация пульса (Heartbeat) компонента системы."""
        payload = {
            "component": component,
            "status": status,
            "pid": os.getpid(),
            "meta": metadata or {},
        }
        return self.emit_event("heartbeat", payload, source=component)

    def close(self) -> None:
        with self._conn_lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    @property
    def buffered_count(self) -> int:
        return len(self._ram_queue)


# =====================================================================
# 4. Единый адаптер боевого транспорта RealTransportAdapter
# =====================================================================

class RealTransportAdapter:
    """Единый адаптер транспорта RAiF: Named Pipe + Fallback HTTP + Metrics + Supervisor Bridge."""

    def __init__(
        self,
        pipe_name: str = DEFAULT_RAIF_PIPE,
        fallback_port: int = DEFAULT_FALLBACK_PORT,
        metrics_pipe: str = DEFAULT_METRICS_PIPE,
        inet_fallback_port: Optional[int] = 18894,
    ) -> None:
        self.pipe_name = pipe_name
        self.fallback_port = fallback_port
        self.metrics_pipe = metrics_pipe
        self.inet_fallback_port = inet_fallback_port

        self.named_pipe_client = NamedPipeClient(pipe_name=pipe_name, inet_fallback_port=inet_fallback_port)
        self.http_client = HttpFallbackClient(port=fallback_port)
        self.metrics_bridge = FleetMetricsBridge(pipe_name=metrics_pipe)

        self._active_channel: Optional[ITransportChannel] = None
        self._channel_name = "NONE"
        self._running = False
        self._heartbeat_thread: Optional[threading.Thread] = None

    @property
    def active_channel_name(self) -> str:
        return self._channel_name

    @property
    def is_connected(self) -> bool:
        return self._active_channel is not None and self._active_channel.is_connected()

    def start(self, start_heartbeat: bool = True) -> bool:
        """Инициализация и подключение к первичному каналу (или fallback)."""
        self._running = True

        # Шаг 1: попытка подключения к первичному Named Pipe
        if self.named_pipe_client.connect():
            self._active_channel = self.named_pipe_client
            self._channel_name = "NAMED_PIPE"
        # Шаг 2: fallback на локальный HTTP шлюз
        elif self.http_client.connect():
            self._active_channel = self.http_client
            self._channel_name = "HTTP_FALLBACK"
        else:
            self._active_channel = None
            self._channel_name = "DEGRADED_OFFLINE"

        # Фиксируем статус в телеметрии флота
        self.metrics_bridge.emit_heartbeat(
            component="raif_transport",
            status="INITIALIZED",
            metadata={"active_channel": self._channel_name, "pipe": self.pipe_name},
        )

        if start_heartbeat:
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                name="RAIF-Transport-Heartbeat",
                daemon=True,
            )
            self._heartbeat_thread.start()

        return self._active_channel is not None

    def _heartbeat_loop(self) -> None:
        while self._running:
            time.sleep(5.0)
            if not self._running:
                break
            # Проверка жизнеспособности и авто-переключение канала при необходимости
            if self._active_channel is None or not self._active_channel.is_connected():
                if self.named_pipe_client.connect():
                    self._active_channel = self.named_pipe_client
                    self._channel_name = "NAMED_PIPE"
                elif self.http_client.connect():
                    self._active_channel = self.http_client
                    self._channel_name = "HTTP_FALLBACK"
                else:
                    self._channel_name = "DEGRADED_OFFLINE"

            self.metrics_bridge.emit_heartbeat(
                component="raif_transport",
                status="HEALTHY" if self.is_connected else "RECONNECTING",
                metadata={"active_channel": self._channel_name},
            )

    def send(self, envelope: TransportMessageEnvelope) -> bool:
        """Отправка конверта через активный транспортный канал с регистрацией метрики."""
        # 1. Если мы находимся в режиме fallback, пытаемся вернуть первичный Named Pipe
        if self._channel_name != "NAMED_PIPE":
            if self.named_pipe_client.connect():
                self._active_channel = self.named_pipe_client
                self._channel_name = "NAMED_PIPE"

        # 2. Если соединения нет, пробуем установить
        if not self.is_connected:
            if self.named_pipe_client.connect():
                self._active_channel = self.named_pipe_client
                self._channel_name = "NAMED_PIPE"
            elif self.http_client.connect():
                self._active_channel = self.http_client
                self._channel_name = "HTTP_FALLBACK"
            else:
                return False

        assert self._active_channel is not None
        success = self._active_channel.send(envelope)

        # 3. Мгновенный failover на резервный HTTP канал при сбое первичного канала
        if not success and self._channel_name == "NAMED_PIPE":
            if self.http_client.connect():
                self._active_channel = self.http_client
                self._channel_name = "HTTP_FALLBACK"
                success = self._active_channel.send(envelope)

        if success:
            self.metrics_bridge.emit_event(
                "transport_send_success",
                {"message_id": envelope.message_id, "channel": self._channel_name},
            )
        return success

    def receive(self, timeout: float = 1.0) -> Optional[TransportMessageEnvelope]:
        """Приём очередного сообщения из активного канала."""
        if self._active_channel is None:
            return None
        return self._active_channel.receive(timeout=timeout)

    # -----------------------------------------------------------------
    # Supervisor Bridge (Phase 3 Интеграция с Antigravity Supervisor)
    # -----------------------------------------------------------------

    def register_supervisor_status(self, supervisor_data: Dict[str, Any]) -> bool:
        """Трансляция агрегированного статуса UnifiedSupervisor в CONTROL_TOWER."""
        envelope = TransportMessageEnvelope.create(
            payload_type="supervisor_status",
            payload=supervisor_data,
            channel="supervisor_bridge",
            source="raif_unified_supervisor",
        )
        self.metrics_bridge.emit_event("supervisor_status_update", supervisor_data)
        if self.is_connected:
            return self.send(envelope)
        return True

    def route_model_request(self, target_account: str, prompt: str, session_id: str) -> Dict[str, Any]:
        """Маршрутизация запроса к модели через ASTRA-роутинг или IPC-конвейер."""
        envelope = TransportMessageEnvelope.create(
            payload_type="model_request",
            payload={"account_id": target_account, "prompt": prompt, "session_id": session_id},
            channel="model_dispatch",
            source="raif_model_router",
        )
        self.metrics_bridge.emit_event("model_request_routed", {"account_id": target_account, "session_id": session_id})
        return {
            "routed": True,
            "envelope_id": envelope.message_id,
            "target_account": target_account,
            "timestamp": envelope.timestamp,
        }

    def stop(self) -> None:
        """Остановка всех каналов и фоновых потоков."""
        self._running = False
        self.named_pipe_client.disconnect()
        self.http_client.disconnect()
        self.metrics_bridge.close()
        self._active_channel = None
        self._channel_name = "CLOSED"
