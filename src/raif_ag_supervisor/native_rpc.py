"""Minimal read-only observer for a running Antigravity Language Server.

An internal Connect RPC is not a stable public API. This module has no host
process discovery, credential writes, account switching, or direct Google calls.
The caller supplies a verified loopback port and an in-memory CSRF value;
neither the token nor the server's raw JSON is ever returned in reports.
"""
from __future__ import annotations

import http.client
import json
import ssl
from dataclasses import dataclass, field
from typing import Callable

_SERVICE = "/exa.language_server_pb.LanguageServerService/"
_ALLOWED = frozenset(("HasAuthToken", "GetAuthStatus"))
_MAX_RESPONSE_BYTES = 16 * 1024


class NativeRpcError(RuntimeError):
    """An allowlisted code only: never propagate raw HTTP/OS/token text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class LocalRpcTarget:
    port: int
    csrf_token: str = field(repr=False, compare=False)
    host: str = "127.0.0.1"

    def __post_init__(self) -> None:
        if self.host != "127.0.0.1":
            raise ValueError("RPC_TARGET_MUST_BE_LOOPBACK")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("RPC_PORT_INVALID")
        value = self.csrf_token
        if (not isinstance(value, str) or not 1 <= len(value) <= 1024
                or any(ord(char) < 33 or ord(char) > 126 for char in value)):
            raise ValueError("RPC_CSRF_HEADER_INVALID")


def _decode_reply(data: bytes) -> dict:
    if not isinstance(data, bytes) or len(data) > _MAX_RESPONSE_BYTES:
        raise NativeRpcError("RPC_RESPONSE_SIZE_INVALID")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise NativeRpcError("RPC_RESPONSE_JSON_INVALID") from None
    if not isinstance(parsed, dict):
        raise NativeRpcError("RPC_RESPONSE_SCHEMA_INVALID")
    return parsed


def invoke_native_rpc(target: LocalRpcTarget, method: str, *, timeout: float = 2.0) -> dict:
    """POST fixed, mutation-free Connect JSON over HTTPS IPv4 loopback only.

    Deliberately no redirects, custom paths, proxy support, or arbitrary body.
    A successful response is NOT proof of a new authenticated account.
    """
    if method not in _ALLOWED:
        raise NativeRpcError("RPC_METHOD_NOT_READONLY_ALLOWLISTED")
    if not 0 < timeout <= 10:
        raise ValueError("RPC_TIMEOUT_INVALID")

    # The installed LS uses a self-signed certificate on a per-process loopback
    # HTTPS port. Disable CA verification for this literal IPv4 loopback ONLY.
    # The caller MUST independently verify PID + start marker + port ownership
    # before acquiring a LocalRpcTarget; this transport does not discover PIDs.
    tls_context = ssl._create_unverified_context()
    conn = http.client.HTTPSConnection(
        "127.0.0.1", target.port, timeout=timeout, context=tls_context,
    )
    try:
        conn.request(
            "POST", _SERVICE + method, body=b"{}",
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "connect-protocol-version": "1",
                "x-codeium-csrf-token": target.csrf_token,
            },
        )
        response = conn.getresponse()
        if response.status != 200:
            raise NativeRpcError("RPC_HTTP_NON_200")
        declared = response.getheader("content-length")
        if declared is not None:
            try:
                n = int(declared)
            except (ValueError, TypeError):
                raise NativeRpcError("RPC_RESPONSE_LENGTH_INVALID") from None
            if n < 0 or n > _MAX_RESPONSE_BYTES:
                raise NativeRpcError("RPC_RESPONSE_SIZE_INVALID")
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
        return _decode_reply(raw)
    except NativeRpcError:
        raise
    except (OSError, http.client.HTTPException, TimeoutError):
        raise NativeRpcError("RPC_TRANSPORT_FAILED") from None
    finally:
        conn.close()


def _bool_field(payload: dict, *names: str) -> bool | None:
    for name in names:
        if name in payload:
            value = payload[name]
            if type(value) is not bool:
                raise NativeRpcError("RPC_FLAG_SCHEMA_INVALID")
            return value
    return None


class NativeRpcObserver:
    """Reduce raw RPC responses to boolean observations and safe error codes."""

    def __init__(
        self,
        target: LocalRpcTarget,
        sender: Callable[[LocalRpcTarget, str], dict] | None = None,
    ) -> None:
        self._target = target
        self._sender = sender or invoke_native_rpc

    def observe(self) -> dict:
        statuses: dict[str, str] = {}
        has_token: bool | None = None
        auth_flag: bool | None = None
        for method in ("HasAuthToken", "GetAuthStatus"):
            try:
                payload = self._sender(self._target, method)
                if not isinstance(payload, dict):
                    raise NativeRpcError("RPC_RESPONSE_SCHEMA_INVALID")
                if method == "HasAuthToken":
                    has_token = _bool_field(payload, "hasToken", "has_token")
                else:
                    result = payload.get("authResult", payload.get("auth_result"))
                    if result is not None and not isinstance(result, dict):
                        raise NativeRpcError("RPC_RESPONSE_SCHEMA_INVALID")
                    if isinstance(result, dict):
                        auth_flag = _bool_field(result, "hasValidAuth", "has_valid_auth")
                statuses[method] = "OK"
            except NativeRpcError as exc:
                statuses[method] = exc.code
            except Exception:
                # User-provided sender errors may embed private URLs/headers.
                statuses[method] = "RPC_OBSERVATION_FAILED"
        return {
            "transport": "CONNECT_JSON_HTTPS_LOOPBACK",
            "method_status": statuses,
            "has_token_reported": has_token,
            "local_auth_flag_untrusted": auth_flag,
            "account_identity_verified": False,
            "provider_access_verified": False,
            "session_switch_verified": False,
            "stream_continuity_verified": False,
        }
