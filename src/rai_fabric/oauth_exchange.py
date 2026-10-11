"""Офлайн-контракт OAuth code exchange и refresh для подписного ChatGPT.

Здесь НЕТ HTTP-клиента, браузера, CLI-команды или автоматического входа.
В тестах используется явно переданная функция транспорта с синтетическими
токенами. Перед будущим сетевым исполнением потребуется отдельный owner gate.
"""
from __future__ import annotations

__version__ = "1.0.0"

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from .oauth_readiness import (
    OAuthCallbackGuard, PrivateAuthorizationCode,
    TOKEN_ENDPOINT, RESOURCE,
)
from .oauth_identity import VerifiedIdentity, confirmed_plan_scope
from .credential_store import LoadedCredential
from .store import FabricError

_MAX_RESPONSE = 512 * 1024
_MAX_TOKEN = 131072
_PLAN_SCOPE = "chatgpt.tokens.use.direct"


class TokenExchangeError(FabricError):
    """Любые диагностические детали провайдера и все токены скрываются."""


@dataclass(frozen=True, repr=False)
class SecretTokenRequest:
    """Запрос к строго фиксированному token endpoint; нельзя печатать body."""
    form: tuple[tuple[str, str], ...] = field(repr=False)
    endpoint: str = TOKEN_ENDPOINT
    method: str = "POST"
    content_type: str = "application/x-www-form-urlencoded"

    def __repr__(self) -> str:
        return "SecretTokenRequest(POST /api/accounts/oauth/token; данные скрыты)"

    def public_report(self) -> dict[str, str | bool]:
        return {"endpoint_host": "auth.openai.com", "method": "POST",
                "sensitive_fields_redacted": True, "request_sent": False}


class TokenTransport(Protocol):
    def __call__(self, request: SecretTokenRequest) -> tuple[int, bytes]: ...


@dataclass(frozen=True, repr=False)
class ParsedTokenResponse:
    """Строго локальная структура с секретами. __repr__ всегда безопасен."""
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    id_token: str | None = field(repr=False)
    scopes: tuple[str, ...]
    expires_in: int

    def __repr__(self) -> str:
        return "ParsedTokenResponse(учётные данные скрыты)"


@dataclass(frozen=True, repr=False)
class ExchangeResult:
    """Метаданные для координатора; личность не печатать."""
    identity: VerifiedIdentity = field(repr=False)
    revision: str
    plan_scope_granted: bool
    operation: str

    def __repr__(self) -> str:
        return f"ExchangeResult(operation={self.operation!r}, личность и токены скрыты)"

    def public_report(self) -> dict[str, str | bool]:
        return {"schema": "RAI_FABRIC_OAUTH_EXCHANGE/1", "operation": self.operation,
                "credential_persisted": True,
                "identity_revalidated_in_operation": self.operation == "authorization_code",
                "identity_bound_to_existing_record": self.operation == "refresh_token",
                "plan_scope_granted": self.plan_scope_granted,
                "model_request_performed": False, "token_values_exposed": False}


def _validate_token(value: Any, field_name: str) -> str:
    if (not isinstance(value, str) or not 16 <= len(value) <= _MAX_TOKEN
            or any(c.isspace() or ord(c) < 32 for c in value)):
        raise TokenExchangeError(f"Недопустимое поле ответа OAuth: {field_name}")
    return value


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise TokenExchangeError("Повторяющееся поле в ответе OAuth")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise TokenExchangeError("Недопустимая числовая константа в ответе OAuth")


def _parse_response(raw: tuple[int, bytes], *, operation: str) -> ParsedTokenResponse:
    if (not isinstance(raw, tuple) or len(raw) != 2
            or type(raw[0]) is not int or not isinstance(raw[1], bytes)
            or len(raw[1]) > _MAX_RESPONSE):
        raise TokenExchangeError("Неверный формат ответа сервера авторизации")
    status, body = raw
    if status != 200:
        # В тело ошибки могут попасть токены, идентификаторы и произвольный HTML.
        # Не выводить его и не повторять exchange при неясном исходе.
        if status in (400, 401, 403):
            raise TokenExchangeError("OAuth отклонён; требуется новый вход или проверка согласия")
        raise TokenExchangeError("OAuth не завершён; автоматический повтор запрещён")
    if not body or len(body) > _MAX_RESPONSE:
        raise TokenExchangeError("Пустой или слишком большой ответ OAuth")
    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    except (ValueError, TypeError, UnicodeError):
        raise TokenExchangeError("Недействительный JSON от сервера авторизации") from None
    if not isinstance(data, dict):
        raise TokenExchangeError("Ответ OAuth должен содержать объект")
    if data.get("token_type") != "Bearer":
        raise TokenExchangeError("Ожидался токен типа Bearer")
    ttl = data.get("expires_in")
    if type(ttl) is not int or not 60 <= ttl <= 86400:
        raise TokenExchangeError("Некорректный срок действия access token")
    scope = data.get("scope")
    if not isinstance(scope, str) or not scope or len(scope) > 2048:
        raise TokenExchangeError("Ответ OAuth не подтверждает выданные разрешения")
    scopes = scope.split()
    if (not scopes or len(scopes) > 24 or len(scopes) != len(set(scopes))
            or any(not name or len(name) > 128 for name in scopes)):
        raise TokenExchangeError("Некорректный перечень OAuth-разрешений")
    access = _validate_token(data.get("access_token"), "access_token")
    refresh = _validate_token(data.get("refresh_token"), "refresh_token")
    raw_id = data.get("id_token")
    if operation == "authorization_code":
        ident = _validate_token(raw_id, "id_token")
    elif operation == "refresh_token":
        # Новый ID-токен при refresh не заменяет ранее валидированный ID-токен:
        # у него может отсутствовать исходный nonce. Не доверяем его claims.
        ident = None
        if raw_id is not None:
            _validate_token(raw_id, "id_token")
    else:
        raise TokenExchangeError("Неизвестная операция OAuth")
    return ParsedTokenResponse(access_token=access, refresh_token=refresh,
                               id_token=ident, scopes=tuple(scopes), expires_in=ttl)


def code_request(code: PrivateAuthorizationCode) -> SecretTokenRequest:
    if not isinstance(code, PrivateAuthorizationCode) or code.client_id == "dynamic_agent_client":
        raise TokenExchangeError("Для обмена нужен выданный client_id")
    return SecretTokenRequest(form=(("grant_type", "authorization_code"),
                                    ("client_id", code.client_id),
                                    ("code", code.code),
                                    ("code_verifier", code.code_verifier),
                                    ("redirect_uri", code.redirect_uri),
                                    ("resource", RESOURCE)))


def refresh_request(credential: Mapping[str, Any]) -> SecretTokenRequest:
    client = credential.get("client_id")
    refresh = credential.get("refresh_token")
    if (not isinstance(client, str) or client == "dynamic_agent_client"
            or not client.startswith("oaiapp_") or len(client) > 256):
        raise TokenExchangeError("Некорректная привязка клиента OAuth")
    _validate_token(refresh, "refresh_token")
    return SecretTokenRequest(form=(("grant_type", "refresh_token"),
                                    ("client_id", client),
                                    ("refresh_token", refresh),
                                    ("resource", RESOURCE)))


def _transport_call(transport: TokenTransport, request: SecretTokenRequest,
                    operation: str) -> ParsedTokenResponse:
    if not callable(transport):
        raise TokenExchangeError("Транспорт OAuth не подключён")
    try:
        reply = transport(request)
    except Exception:
        # Даже RuntimeError из транспорта может содержать токены, URL с query и т.д.
        raise TokenExchangeError("Транспорт OAuth завершился без подтверждённого ответа") from None
    return _parse_response(reply, operation=operation)


def exchange_code_offline(*, guard: OAuthCallbackGuard, callback_url: str,
                          transport: TokenTransport, keys: Any, vault: Any,
                          now: int | None = None,
                          returning_identity: VerifiedIdentity | None = None,
                          expected_revision: str | None = None) -> ExchangeResult:
    """Обмен с внедрённым тестовым транспортом, без встроенного сетевого клиента.

    После положительного ответа проверяет реальную подпись ID-токена через
    TrustedOpenAIKeys и сохраняет токены атомарно. Не возвращает сами токены.
    """
    from .trusted_jwks import TrustedOpenAIKeys
    if not isinstance(keys, TrustedOpenAIKeys):
        raise TokenExchangeError("Нужен доверенный проверяющий JWKS")
    if type(now) is not int and now is not None:
        raise TokenExchangeError("Некорректное локальное время")
    now = int(time.time()) if now is None else now
    if now < 0:
        raise TokenExchangeError("Некорректное локальное время")
    if returning_identity is not None and (not isinstance(returning_identity, VerifiedIdentity)
                                           or expected_revision is None):
        raise TokenExchangeError("Для повторного входа требуется проверенная ревизия")
    if returning_identity is None and expected_revision is not None:
        raise TokenExchangeError("Ревизия не соответствует новому входу")
    if not isinstance(guard, OAuthCallbackGuard):
        raise TokenExchangeError("Нужен одноразовый защитник callback")
    callback = guard.consume_private(callback_url)
    if not callback.client_id.startswith("oaiapp_"):
        raise TokenExchangeError("OAuth не вернул выданный client_id")
    response = _transport_call(transport, code_request(callback), "authorization_code")
    identity = keys.verify(response.id_token, issued_client_id=callback.client_id,
                           expected_nonce=callback.nonce)
    if returning_identity is not None and (
            returning_identity.client_id != identity.client_id
            or returning_identity.issuer != identity.issuer
            or returning_identity.subject != identity.subject):
        raise TokenExchangeError("Повторный вход привязан к другой учётной записи")
    if "offline_access" not in response.scopes:
        raise TokenExchangeError("Нельзя создать обновляемый сеанс без offline_access")
    record = dict(issuer=identity.issuer, client_id=identity.client_id,
                  subject=identity.subject, access_token=response.access_token,
                  refresh_token=response.refresh_token, id_token=response.id_token,
                  token_type="Bearer", scopes=list(response.scopes),
                  ext_agent_host_id=callback.host_id, saved_at=now,
                  expires_at=now + response.expires_in)
    try:
        revision = vault.save(identity, record, expected_revision=expected_revision)
    except Exception:
        raise TokenExchangeError("Сохранение OAuth не подтверждено; повтор кода запрещён") from None
    return ExchangeResult(identity=identity, revision=revision,
                          plan_scope_granted=confirmed_plan_scope(identity, " ".join(response.scopes)),
                          operation="authorization_code")


def refresh_offline(*, identity: VerifiedIdentity, vault: Any,
                    transport: TokenTransport, now: int | None = None,
                    early_seconds: int = 300) -> ExchangeResult:
    """Один refresh под межпроцессной блокировкой НА ВРЕМЯ запроса к серверу.

    После успешного ответа refresh-токен уже мог быть использован провайдером:
    ошибка локальной записи означает BLOCKED и повтор запрещён до сверки.
    """
    if not isinstance(identity, VerifiedIdentity):
        raise TokenExchangeError("Не подтверждена личность для refresh")
    if type(early_seconds) is not int or not 0 <= early_seconds <= 3600:
        raise TokenExchangeError("Некорректное окно обновления")
    if type(now) is not int and now is not None:
        raise TokenExchangeError("Некорректное локальное время")
    now = int(time.time()) if now is None else now
    if now < 0:
        raise TokenExchangeError("Некорректное локальное время")
    not_due = False
    try:
        with vault.refresh_lock(identity):
            current: LoadedCredential = vault.load(identity)
            old = current.credentials
            if old["expires_at"] - now > early_seconds:
                # Выходим ИЗ контекста штатно и удаляем блокировку.
                not_due = True
            else:
                response = _transport_call(transport, refresh_request(old), "refresh_token")
                if response.refresh_token == old["refresh_token"]:
                    raise TokenExchangeError("Сервер не заменил refresh token; обновление заблокировано")
                if "offline_access" not in response.scopes:
                    raise TokenExchangeError("Обновление утратило offline_access; требуется новый вход")
                new = dict(old)
                new.update(access_token=response.access_token,
                           refresh_token=response.refresh_token,
                           scopes=list(response.scopes),
                           saved_at=now, expires_at=now + response.expires_in)
                revision = vault.save(identity, new, expected_revision=current.revision)
    except TokenExchangeError:
        # .refresh.lock сохраняется при неопределённом результате сервера.
        raise
    except Exception:
        raise TokenExchangeError("Обновление OAuth не подтверждено; повтор запрещён до сверки") from None
    if not_due:
        raise TokenExchangeError("Срок обновления ещё не наступил")
    return ExchangeResult(identity=identity, revision=revision,
                          plan_scope_granted=confirmed_plan_scope(identity, " ".join(response.scopes)),
                          operation="refresh_token")
