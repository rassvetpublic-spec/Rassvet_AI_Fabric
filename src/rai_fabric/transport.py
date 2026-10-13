# -*- coding: utf-8 -*-
"""
rai_fabric.transport - Мост обратной совместимости для пакета transport (Stage R25).
Реэкспортирует интерфейсы и адаптеры боевого IPC-транспорта RAiF.

Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.2) / RAiF 10.7 Stage R25 / Rassvet_AI_Fabric#15.
"""

from __future__ import annotations

__version__ = "1.0.0"

from transport.ipc_channel import (
    ITransportChannel,
    TransportError,
    TransportMessageEnvelope,
    TransportStatus,
)
from transport.real_transport import (
    DEFAULT_FALLBACK_PORT,
    DEFAULT_METRICS_PIPE,
    DEFAULT_RAIF_PIPE,
    FleetMetricsBridge,
    HttpFallbackClient,
    HttpFallbackServer,
    NamedPipeClient,
    NamedPipeServer,
    RealTransportAdapter,
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
