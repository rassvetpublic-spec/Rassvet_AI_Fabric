# -*- coding: utf-8 -*-
"""
transport - Пакет реального межпроцессного транспорта (IPC) Rassvet AI Fabric (Stage R25).
Включает Named Pipe транспорт Windows, резервный WebSocket/HTTP канал и стриминг метрик.

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.2) / RAiF 10.7 Stage R25 / Rassvet_AI_Fabric#15.
"""

from __future__ import annotations

__version__ = "1.0.0"

from .ipc_channel import (
    ITransportChannel,
    TransportMessageEnvelope,
    TransportStatus,
    TransportError,
)
from .real_transport import (
    NamedPipeServer,
    NamedPipeClient,
    HttpFallbackServer,
    HttpFallbackClient,
    FleetMetricsBridge,
    RealTransportAdapter,
    DEFAULT_RAIF_PIPE,
    DEFAULT_FALLBACK_PORT,
    DEFAULT_METRICS_PIPE,
)

__all__ = [
    "__version__",
    "ITransportChannel",
    "TransportMessageEnvelope",
    "TransportStatus",
    "TransportError",
    "NamedPipeServer",
    "NamedPipeClient",
    "HttpFallbackServer",
    "HttpFallbackClient",
    "FleetMetricsBridge",
    "RealTransportAdapter",
    "DEFAULT_RAIF_PIPE",
    "DEFAULT_FALLBACK_PORT",
    "DEFAULT_METRICS_PIPE",
]
