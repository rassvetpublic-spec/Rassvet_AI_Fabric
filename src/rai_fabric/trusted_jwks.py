"""Доверенное получение ключей OpenAI по OIDC Discovery с fail-closed кешем.

Никакой сетевой операции при импорте модуля. Не принимает URL из токена,
не следует HTTP-перенаправлениям и не читает произвольные OIDC-провайдеры.
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, OpenerDirector, ProxyHandler, Request, build_opener
import ssl

from .oauth_identity import ISSUER, IdentityVerificationError, VerifiedIdentity, verify_id_token
from .store import FabricError

DISCOVERY_URL = "https://auth.openai.com/.well-known/openid-configuration"
JWKS_URL = "https://auth.openai.com/.well-known/jwks.json"
_MAX_DISCOVERY_BYTES = 32 * 1024
_MAX_JWKS_BYTES = 128 * 1024
_KID_RE = re.compile(r"^[a-zA-Z0-9._:\-]{1,256}$")


class TrustedKeyError(FabricError):
    """Недоверенный источник ключей: сообщение намеренно не содержит URL извне."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TrustedKeyError("Перенаправление при получении ключей запрещено")


def _decode_strict_json(raw: bytes, limit: int) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not 2 <= len(raw) <= limit:
        raise TrustedKeyError("Недопустимый размер ответа OIDC")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise TrustedKeyError("Повторяющееся поле в документе OIDC")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NaN")))
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
        raise TrustedKeyError("Повреждён документ OIDC") from None
    if not isinstance(value, dict):
        raise TrustedKeyError("Документ OIDC должен быть объектом")
    return value


def _validate_discovery(raw: bytes) -> None:
    doc = _decode_strict_json(raw, _MAX_DISCOVERY_BYTES)
    if (doc.get("issuer") != ISSUER or doc.get("jwks_uri") != JWKS_URL):
        raise TrustedKeyError("OIDC Discovery не совпадает с доверенным издателем")
    for optional in ("authorization_endpoint", "token_endpoint"):
        if optional in doc and not (isinstance(doc[optional], str)
                                    and doc[optional].startswith(ISSUER + "/")
                                    and "#" not in doc[optional]
                                    and "?" not in doc[optional]):
            raise TrustedKeyError("Недопустимый адрес служебного OIDC endpoint")


def _validate_jwks(raw: bytes) -> dict[str, Any]:
    doc = _decode_strict_json(raw, _MAX_JWKS_BYTES)
    keys = doc.get("keys")
    if not isinstance(keys, list) or not 1 <= len(keys) <= 64:
        raise TrustedKeyError("Недопустимый набор публичных ключей")
    seen = set()
    checked = []
    for key in keys:
        if not isinstance(key, dict):
            raise TrustedKeyError("Некорректный элемент JWKS")
        kid = key.get("kid")
        if not isinstance(kid, str) or not _KID_RE.fullmatch(kid) or kid in seen:
            raise TrustedKeyError("Некорректный либо повторяющийся идентификатор ключа")
        seen.add(kid)
        if (key.get("kty") != "RSA" or key.get("alg", "RS256") != "RS256"
                or key.get("use", "sig") != "sig"
                or ("key_ops" in key and key["key_ops"] != ["verify"])
                or not isinstance(key.get("n"), str) or not isinstance(key.get("e"), str)
                or not 300 <= len(key["n"]) <= 2048 or not 1 <= len(key["e"]) <= 16
                or any(x in key for x in ("d", "p", "q", "dp", "dq", "qi", "oth", "x5u", "jku", "jwk"))):
            raise TrustedKeyError("Набор содержит неподходящий ключ подписи")
        checked.append(dict(key))
    return {"keys": checked}


def _https_get_once(url: str, cap: int) -> bytes:
    """TLS со стандартным доверенным CA, без proxy, cookie, редиректов."""
    if url not in (DISCOVERY_URL, JWKS_URL):
        raise TrustedKeyError("Запрос к недоверенному адресу запрещён")
    opener: OpenerDirector = build_opener(ProxyHandler({}),
                                         HTTPSHandler(context=ssl.create_default_context()),
                                         _NoRedirect())
    request = Request(url, headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                      method="GET")
    try:
        with opener.open(request, timeout=8) as response:
            if response.status != 200:
                raise TrustedKeyError("OIDC endpoint вернул ошибку")
            if response.geturl() != url:
                raise TrustedKeyError("Непредвиденное перенаправление OIDC")
            size_hint = response.headers.get("Content-Length")
            if size_hint is not None:
                try:
                    size = int(size_hint)
                except ValueError:
                    raise TrustedKeyError("Некорректная длина документа OIDC") from None
                if size < 2 or size > cap:
                    raise TrustedKeyError("Слишком большой документ OIDC")
            content_type = response.headers.get_content_type()
            if content_type not in ("application/json", "application/jwk-set+json"):
                raise TrustedKeyError("OIDC endpoint вернул неподдерживаемый тип данных")
            value = response.read(cap + 1)
            if len(value) > cap:
                raise TrustedKeyError("Превышен лимит размера ответа OIDC")
            return value
    except TrustedKeyError:
        raise
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        raise TrustedKeyError("Не удалось безопасно получить OIDC-ключи") from None


@dataclass(frozen=True)
class KeyCacheStatus:
    """Служебная статистика без token, subject, kid и сторонних URL."""
    has_fresh_keys: bool
    refresh_count: int


class TrustedOpenAIKeys:
    """Доверенный OIDC-провайдер с ограниченным обновлением при смене kid.

    Запросы выполняются только после явного вызова get_jwks/verify.
    Использует монотонное время; после истечения TTL stale-ключи НЕ применяются.
    """

    def __init__(self, *, ttl_seconds: int = 600, retry_delay_seconds: int = 30,
                 download: Callable[[str, int], bytes] | None = None,
                 clock: Callable[[], float] | None = None):
        if (type(ttl_seconds) is not int or not 30 <= ttl_seconds <= 3600
                or type(retry_delay_seconds) is not int
                or not 1 <= retry_delay_seconds <= ttl_seconds):
            raise TrustedKeyError("Некорректные интервалы обновления JWKS")
        self._ttl = ttl_seconds
        self._retry_delay = retry_delay_seconds
        self._download = download or _https_get_once
        self._clock = clock or time.monotonic
        self._keys: dict[str, Any] | None = None
        self._last_fetch: float | None = None
        self._refreshes = 0

    def status(self) -> KeyCacheStatus:
        return KeyCacheStatus(has_fresh_keys=self._is_fresh(), refresh_count=self._refreshes)

    def _is_fresh(self) -> bool:
        return (self._keys is not None and self._last_fetch is not None
                and 0 <= self._clock() - self._last_fetch < self._ttl)

    def _fetch(self) -> dict[str, Any]:
        try:
            discovery = self._download(DISCOVERY_URL, _MAX_DISCOVERY_BYTES)
            _validate_discovery(discovery)
            jwks = _validate_jwks(self._download(JWKS_URL, _MAX_JWKS_BYTES))
        except TrustedKeyError:
            raise
        except Exception:
            raise TrustedKeyError("Недоверенный или недоступный источник OIDC") from None
        self._keys = jwks
        self._last_fetch = self._clock()
        self._refreshes += 1
        return jwks

    def get_jwks(self, *, key_id: str | None = None) -> Mapping[str, Any]:
        """Обновление при отсутствии/истечении TTL и однократно при новом kid."""
        if key_id is not None and (not isinstance(key_id, str) or not _KID_RE.fullmatch(key_id)):
            raise TrustedKeyError("Некорректный идентификатор ключа токена")
        if not self._is_fresh():
            self._fetch()
        if key_id is not None and not any(k["kid"] == key_id for k in self._keys["keys"]):
            if self._last_fetch is not None and self._clock() - self._last_fetch < self._retry_delay:
                raise TrustedKeyError("Подписывающий ключ не найден, обновление ограничено")
            self._fetch()
            if not any(k["kid"] == key_id for k in self._keys["keys"]):
                raise TrustedKeyError("Подписывающий ключ отсутствует после обновления")
        return {"keys": [dict(k) for k in self._keys["keys"]]}

    def verify(self, token: str, *, issued_client_id: str,
               expected_nonce: str) -> VerifiedIdentity:
        """Выбирает набор по untrusted kid, но доверяет только проверенной подписи."""
        if (not isinstance(token, str) or not 32 <= len(token) <= 32768
                or token.count(".") != 2):
            raise IdentityVerificationError("Некорректный формат ID-токена")
        try:
            import jwt
            header = jwt.get_unverified_header(token)
        except Exception:  # намеренно не раскрываем диагностику JWT
            raise IdentityVerificationError("Некорректный заголовок ID-токена") from None
        if (not isinstance(header, dict) or header.get("alg") != "RS256"
                or not isinstance(header.get("kid"), str)
                or any(x in header for x in ("jwk", "jku", "x5u", "x5c", "crit"))):
            raise IdentityVerificationError("Недопустимый заголовок ID-токена")
        jwks = self.get_jwks(key_id=header["kid"])
        return verify_id_token(token, jwks=jwks, issued_client_id=issued_client_id,
                               expected_nonce=expected_nonce)
