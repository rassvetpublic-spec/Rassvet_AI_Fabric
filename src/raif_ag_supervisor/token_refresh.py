# -*- coding: utf-8 -*-
"""
src.raif_ag_supervisor.token_refresh - Управление свежестью и форматированием токенов Google OAuth для Antigravity.
Стандарт: BPR5 NextGen (v5.1.0-alpha / R3.3) / MTD 011011.
"""
from __future__ import annotations

__version__ = "1.0.0"

import os
import sys
import time
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

# Google Cloud Code / Antigravity OAuth client IDs из аудита binary language_server
GOOGLE_ANTIGRAVITY_CLIENT_ID = "884354919052-36trc1jjb3tguiac32ov6cod268c5blh.apps.googleusercontent.com"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

DEFAULT_AGTOOLS_ACCOUNTS_DIR = Path.home() / ".antigravity_tools" / "accounts"


class TokenRefreshError(RuntimeError):
    """Безопасная ошибка без утечки токенов и секретов."""


@dataclass(frozen=True)
class FormattedAccountCredential:
    account_id: str
    email_masked: str
    has_fresh_access: bool
    expires_in_seconds: float
    payload: Dict[str, Any] = field(repr=False)

    def safe_summary(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "email_masked": self.email_masked,
            "has_fresh_access": self.has_fresh_access,
            "expires_in_seconds": round(self.expires_in_seconds, 1),
        }


def mask_email(email: str) -> str:
    """Маскирование email для безопасного логирования: user@domain.com -> u***r@domain.com."""
    if not email or "@" not in email:
        return "redacted"
    parts = email.split("@", 1)
    user, domain = parts[0], parts[1]
    if len(user) <= 2:
        masked_user = user[0] + "*"
    else:
        masked_user = user[0] + "*" * (len(user) - 2) + user[-1]
    return f"{masked_user}@{domain}"


def format_antigravity_credential_payload(
    access_token: str,
    refresh_token: str,
    expiry_timestamp: float,
    id_token: str = "",
    auth_method: str = "consumer",
) -> Dict[str, Any]:
    """Формирует канонический JSON payload для Credential Manager gemini:antigravity."""
    if not access_token or not refresh_token:
        raise TokenRefreshError("Both access_token and refresh_token are required")

    dt = datetime.fromtimestamp(expiry_timestamp, timezone.utc)
    expiry_rfc3339 = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "token": {
            "access_token": access_token,
            "token_type": "Bearer",
            "refresh_token": refresh_token,
            "expiry": expiry_rfc3339,
        },
        "auth_method": auth_method,
        "id_token": id_token or "",
    }


def refresh_google_access_token(
    refresh_token: str,
    client_id: str = GOOGLE_ANTIGRAVITY_CLIENT_ID,
    timeout_seconds: float = 6.0,
) -> Dict[str, Any]:
    """Прямое обновление access-токена через Google OAuth 2.0 endpoint по refresh-токену."""
    if not refresh_token or not isinstance(refresh_token, str):
        raise TokenRefreshError("Invalid refresh token")

    data = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_TOKEN_ENDPOINT,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read(64 * 1024)
            parsed = json.loads(body.decode("utf-8"))
            if not isinstance(parsed, dict) or "access_token" not in parsed:
                raise TokenRefreshError("Invalid response from Google OAuth token endpoint")
            return parsed
    except urllib.error.HTTPError as exc:
        raise TokenRefreshError(f"Google OAuth refresh HTTP error: {exc.code}") from None
    except Exception as exc:
        raise TokenRefreshError("Google OAuth network refresh failed") from None


def load_cached_profiles(
    accounts_dir: Path = DEFAULT_AGTOOLS_ACCOUNTS_DIR,
    min_ttl_seconds: float = 120.0,
) -> List[FormattedAccountCredential]:
    """Загружает локально сохраненные профили из директории кэша и форматирует их."""
    if not accounts_dir.exists():
        return []

    now = time.time()
    results = []

    for file_path in sorted(accounts_dir.glob("*.json")):
        try:
            raw = file_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                continue
            
            token_obj = data.get("token", {})
            if not isinstance(token_obj, dict):
                continue

            access_token = token_obj.get("access_token", "")
            refresh_token = token_obj.get("refresh_token", "")
            expiry_ts = float(token_obj.get("expiry_timestamp", 0.0))
            email = data.get("email", "") or token_obj.get("email", "")
            id_token = token_obj.get("id_token", "")

            if not access_token or not refresh_token:
                continue

            remaining = expiry_ts - now
            is_fresh = remaining > min_ttl_seconds

            payload = format_antigravity_credential_payload(
                access_token=access_token,
                refresh_token=refresh_token,
                expiry_timestamp=expiry_ts,
                id_token=id_token,
            )

            results.append(
                FormattedAccountCredential(
                    account_id=data.get("id", file_path.stem),
                    email_masked=mask_email(email),
                    has_fresh_access=is_fresh,
                    expires_in_seconds=remaining,
                    payload=payload,
                )
            )
        except Exception:
            continue

    return results
