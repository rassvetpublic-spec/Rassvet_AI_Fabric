"""Подготовка авторизации ChatGPT по подписке без сети и доступа к секретам.

Модуль не открывает браузер, не запускает Codex, не получает токены и не
утверждает наличие у пользователя права на модели. После проверки callback
обмен кода и проверка подписи ID-токена остаются отдельным этапом.
"""
from __future__ import annotations

__version__ = "1.0.0"

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlsplit

from .store import FabricError


AUTHORIZATION_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_ENDPOINT = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
REQUESTED_SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
_DYNAMICAL_CLIENT_ID = "dynamic_agent_client"
_CALLBACK_PATH = "/auth/callback"


class OAuthReadinessError(FabricError):
    """Неверная конфигурация или callback; никаких токенов не выдаётся."""


@dataclass(frozen=True, repr=False)
class OAuthAttempt:
    """Одноразовая попытка: значения verifier/state/nonce нельзя журналировать."""

    client_id: str
    host_id: str
    redirect_uri: str
    authorization_url: str = field(repr=False)
    state: str = field(repr=False)
    nonce: str = field(repr=False)
    code_verifier: str = field(repr=False)

    def public_report(self) -> dict[str, str | bool]:
        """Только неизменные несекретные метаданные для evidence."""
        return {
            "schema": "RAI_FABRIC_CHATGPT_OAUTH_READINESS/1",
            "verdict": "PARTIAL",
            "provider": "chatgpt-plan",
            "redirect_host": "127.0.0.1",
            "redirect_path": _CALLBACK_PATH,
            "pkce_method": "S256",
            "oauth_authorization_completed": False,
            "id_token_signature_verified": False,
            "subscription_permission_verified": False,
            "model_inference_executed": False,
            "cursor": "AWAIT_USER_AUTHORIZATION_AND_ID_TOKEN_VERIFICATION",
        }


def _valid_identifier(value: str, name: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise OAuthReadinessError(f"Недопустимое значение: {name}")
    if any(not (c.isascii() and (c.isalnum() or c in "-_:.")) for c in value):
        raise OAuthReadinessError(f"Недопустимые символы: {name}")
    return value


def new_authorization_attempt(*, host_id: str, callback_port: int,
                              client_id: str = _DYNAMICAL_CLIENT_ID,
                              agent_name: str = "rassvet_ai_fabric") -> OAuthAttempt:
    """Генерирует параметры и URL, но никогда сам не инициирует вход или сетевой запрос."""
    host_id = _valid_identifier(host_id, "host_id")
    client_id = _valid_identifier(client_id, "client_id")
    if type(callback_port) is not int or not 1024 <= callback_port <= 65535:
        raise OAuthReadinessError("Callback должен использовать отдельный локальный порт")
    if client_id == _DYNAMICAL_CLIENT_ID:
        _valid_identifier(agent_name, "agent_name")
    redirect_uri = f"http://127.0.0.1:{callback_port}{_CALLBACK_PATH}"
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    fields = {
        "response_type": "code",
        "client_id": client_id,
        "ext_agent_host_id": host_id,
        "redirect_uri": redirect_uri,
        "scope": REQUESTED_SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if client_id == _DYNAMICAL_CLIENT_ID:
        fields["agent_name_hint"] = agent_name
    url = f"{AUTHORIZATION_URL}?{urlencode(fields)}"
    return OAuthAttempt(client_id=client_id, host_id=host_id, redirect_uri=redirect_uri,
                        authorization_url=url, state=state, nonce=nonce,
                        code_verifier=verifier)


def validate_authorization_callback(attempt: OAuthAttempt, callback_url: str) -> dict[str, str | bool]:
    """Проверяет одноразовый callback без обмена кода и без вывода самих секретов.

    Успешный ответ разрешает только переход к отдельному шлюзу обмена токенов:
    ни ID-токен, ни подписка, ни будущая модель пока не подтверждены.
    """
    if not isinstance(attempt, OAuthAttempt) or not isinstance(callback_url, str):
        raise OAuthReadinessError("Неверный тип данных callback")
    try:
        target = urlsplit(callback_url)
        expected = urlsplit(attempt.redirect_uri)
        if (target.scheme != expected.scheme or target.hostname != "127.0.0.1"
                or target.port != expected.port or target.path != _CALLBACK_PATH
                or target.username is not None or target.password is not None
                or target.fragment or target.netloc != expected.netloc):
            raise OAuthReadinessError("Callback поступил не на разрешённый loopback адрес")
        if len(callback_url) > 16384:
            raise OAuthReadinessError("Callback превышает разрешённый размер")
        params = parse_qs(target.query, keep_blank_values=True, strict_parsing=True,
                          encoding="utf-8", errors="strict", max_num_fields=12)
    except (ValueError, UnicodeDecodeError) as exc:
        raise OAuthReadinessError("Некорректная форма callback") from exc
    if any(len(values) != 1 for values in params.values()):
        raise OAuthReadinessError("Повторяющиеся параметры callback запрещены")
    state = params.get("state", [""])[0]
    if not hmac.compare_digest(state, attempt.state):
        raise OAuthReadinessError("OAuth state не совпадает с текущей попыткой")
    if "error" in params:
        # Не отражаем error_description, чтобы не переносить произвольный текст в логи.
        raise OAuthReadinessError("Авторизация отклонена или прервана в браузере")
    code = params.get("code", [""])[0]
    if not code or len(code) > 8192:
        raise OAuthReadinessError("Отсутствует корректный одноразовый код авторизации")
    returned_client = params.get("client_id", [""])[0]
    if attempt.client_id == _DYNAMICAL_CLIENT_ID:
        if not returned_client or returned_client == _DYNAMICAL_CLIENT_ID:
            raise OAuthReadinessError("Динамическая регистрация не вернула выданный client_id")
        _valid_identifier(returned_client, "issued_client_id", maximum=256)
    elif returned_client and returned_client != attempt.client_id:
        raise OAuthReadinessError("Callback пытается подменить ранее зарегистрированный клиент")
    # Код НЕ возвращаем — во избежание случайной записи в журнал. Код должен
    # храниться временно в приватном callback-обработчике следующего этапа.
    return {
        "schema": "RAI_FABRIC_CHATGPT_OAUTH_CALLBACK/1",
        "verdict": "PARTIAL",
        "state_verified": True,
        "issued_client_id_present": bool(returned_client),
        "authorization_code_exchange_completed": False,
        "id_token_signature_verified": False,
        "subscription_permission_verified": False,
        "cursor": "TOKEN_EXCHANGE_REQUIRED_IN_SECURE_HANDLER",
    }


def plan_scope_granted(scopes: str | None) -> bool:
    """Только предикат для уже полученного ответа token endpoint; не проверяет идентичность."""
    if not isinstance(scopes, str):
        return False
    return "chatgpt.tokens.use.direct" in set(scopes.split())


class OAuthCallbackGuard:
    """Одноразовый потребитель callback; отвергает повтор даже при верном state."""

    def __init__(self, attempt: OAuthAttempt) -> None:
        if not isinstance(attempt, OAuthAttempt):
            raise OAuthReadinessError("Ожидается подтверждённая локальная попытка")
        self._attempt = attempt
        self._consumed = False

    def consume(self, callback_url: str) -> dict[str, str | bool]:
        if self._consumed:
            raise OAuthReadinessError("Повторное использование callback запрещено")
        report = validate_authorization_callback(self._attempt, callback_url)
        self._consumed = True
        return report

    def consume_private(self, callback_url: str) -> "PrivateAuthorizationCode":
        """Одноразово возвращает код ТОЛЬКО вызывающему доверенному обработчику.

        Не сохраняйте возвращённый объект в SQLite, журнале или checkpoint.
        """
        if self._consumed:
            raise OAuthReadinessError("Повторное использование callback запрещено")
        # До извлечения кода проверяем state, точный адрес и выданный client_id.
        validate_authorization_callback(self._attempt, callback_url)
        self._consumed = True
        values = parse_qs(urlsplit(callback_url).query, keep_blank_values=True,
                          strict_parsing=True, max_num_fields=12)
        client = values.get("client_id", [self._attempt.client_id])[0]
        return PrivateAuthorizationCode(
            client_id=client,
            code=values["code"][0],
            code_verifier=self._attempt.code_verifier,
            redirect_uri=self._attempt.redirect_uri,
            host_id=self._attempt.host_id,
            nonce=self._attempt.nonce,
        )


@dataclass(frozen=True, repr=False)
class PrivateAuthorizationCode:
    """Чувствительные параметры, доступные только доверенному локальному коду."""
    client_id: str
    code: str = field(repr=False)
    code_verifier: str = field(repr=False)
    redirect_uri: str
    host_id: str
    nonce: str = field(repr=False)

    def __repr__(self) -> str:
        return "PrivateAuthorizationCode(секреты скрыты)"
