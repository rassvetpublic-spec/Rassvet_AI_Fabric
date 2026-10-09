"""Проверка OpenID Connect ID-токена на доверенных JWKS без сетевых запросов.

Это независимый, изолированный от CLI модуль. Проверка подписи использует
сопровождаемую библиотеку PyJWT[crypto], а не собственную реализацию RSA.
Набор JWKS обязан поступать из проверенного OIDC discovery по HTTPS; модуль
не принимает адреса ключей из заголовка токена.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Mapping

from .store import FabricError

ISSUER = "https://auth.openai.com"
_PLAN_SCOPE = "chatgpt.tokens.use.direct"


class IdentityVerificationError(FabricError):
    """Проверка личности отклонена; исключение не содержит секретов."""


@dataclass(frozen=True, repr=False)
class VerifiedIdentity:
    """Подтверждённые метаданные без исходного JWT и идентификаторов сессий."""

    issuer: str
    client_id: str
    subject: str
    issued_at: int
    expires_at: int

    def __repr__(self) -> str:
        return "VerifiedIdentity(подпись и claims проверены; личность скрыта)"

    def public_report(self) -> dict[str, str | bool]:
        """Для общего журнала без персонального subject, email и токенов."""
        return {
            "schema": "RAI_FABRIC_OIDC_IDENTITY/1",
            "issuer": self.issuer,
            "signature_verified": True,
            "identity_verified": True,
            "plan_permission_verified": False,
            "inference_executed": False,
        }


def verify_id_token(
    token: str,
    *,
    jwks: Mapping[str, Any],
    issued_client_id: str,
    expected_nonce: str,
    issuer: str = ISSUER,
    leeway_seconds: int = 5,
) -> VerifiedIdentity:
    """Проверяет JWT по ранее полученному доверенному набору ключей.

    Никакой JWT не принимается до проверки подписи, сроков, issuer, audience,
    оригинального nonce и присутствия subject. Только RS256; HS256, 'none',
    удалённые URL ключей и ключи из заголовка токена запрещены.
    """
    if (not isinstance(token, str) or not 32 <= len(token) <= 32768
            or token.count(".") != 2):
        raise IdentityVerificationError("Некорректный формат ID-токена")
    if (not isinstance(issued_client_id, str) or not issued_client_id
            or issued_client_id == "dynamic_agent_client" or len(issued_client_id) > 256):
        raise IdentityVerificationError("Нужен выданный, а не динамический client_id")
    if not isinstance(expected_nonce, str) or len(expected_nonce) < 16:
        raise IdentityVerificationError("Не задан исходный nonce авторизации")
    if issuer != ISSUER:
        raise IdentityVerificationError("Недопустимый ожидаемый issuer")
    if type(leeway_seconds) is not int or not 0 <= leeway_seconds <= 30:
        raise IdentityVerificationError("Недопустимый допуск времени")
    if not isinstance(jwks, Mapping) or not isinstance(jwks.get("keys"), list):
        raise IdentityVerificationError("Отсутствует доверенный набор JWKS")
    if not 1 <= len(jwks["keys"]) <= 64:
        raise IdentityVerificationError("Некорректное количество ключей JWKS")

    try:
        import jwt
    except ImportError:
        raise IdentityVerificationError(
            "Для проверки подписи установите дополнительный пакет: pip install '.[security]'"
        ) from None

    try:
        header = jwt.get_unverified_header(token)
    except (jwt.PyJWTError, ValueError, TypeError):
        raise IdentityVerificationError("Повреждён заголовок ID-токена") from None
    if (not isinstance(header, dict) or header.get("alg") != "RS256"
            or not isinstance(header.get("kid"), str) or not header["kid"]
            or len(header["kid"]) > 256
            or any(name in header for name in ("jwk", "jku", "x5u", "crit", "x5c"))
            or header.get("typ", "JWT") != "JWT"):
        raise IdentityVerificationError("Неподдерживаемый алгоритм или заголовок ID-токена")

    keys = [key for key in jwks["keys"]
            if isinstance(key, dict) and key.get("kid") == header["kid"]]
    if len(keys) != 1:
        raise IdentityVerificationError("Ключ подписи не найден или неоднозначен")
    key = keys[0]
    if (key.get("kty") != "RSA" or key.get("alg", "RS256") != "RS256"
            or key.get("use", "sig") != "sig"
            or ("key_ops" in key and key["key_ops"] != ["verify"])
            or any(name in key for name in ("d", "p", "q", "dp", "dq", "qi", "oth"))):
        raise IdentityVerificationError("JWKS не содержит допустимого публичного ключа подписи")

    try:
        verified_key = jwt.PyJWK.from_dict(key, algorithm="RS256").key
        if getattr(verified_key, "key_size", 0) < 2048:
            raise IdentityVerificationError("Недостаточная длина ключа RSA")
        claims = jwt.decode(
            token,
            key=verified_key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=issued_client_id,
            leeway=leeway_seconds,
            options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"]},
        )
    except IdentityVerificationError:
        raise
    except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
        raise IdentityVerificationError("Подпись или обязательные поля ID-токена недействительны") from None

    # Дополнительные ограничения OIDC: JWT с несколькими aud должен иметь azp.
    audience = claims["aud"]
    if isinstance(audience, list):
        if not audience or not all(isinstance(a, str) for a in audience):
            raise IdentityVerificationError("Некорректная аудитория токена")
        if len(audience) > 1 and claims.get("azp") != issued_client_id:
            raise IdentityVerificationError("Отсутствует верный azp при нескольких аудиториях")
    elif not isinstance(audience, str):
        raise IdentityVerificationError("Некорректная аудитория токена")
    if "azp" in claims and claims["azp"] != issued_client_id:
        raise IdentityVerificationError("Подмена авторизованной стороны токена")
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not hmac.compare_digest(nonce, expected_nonce):
        raise IdentityVerificationError("OIDC nonce не совпадает")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > 512 or any(ord(c) < 32 for c in sub):
        raise IdentityVerificationError("Некорректный идентификатор субъекта")
    for field in ("iat", "exp"):
        if type(claims[field]) is not int:
            raise IdentityVerificationError("Некорректная временная метка ID-токена")
    if claims["exp"] <= claims["iat"]:
        raise IdentityVerificationError("Время окончания токена предшествует выдаче")
    return VerifiedIdentity(
        issuer=issuer,
        client_id=issued_client_id,
        subject=sub,
        issued_at=claims["iat"],
        expires_at=claims["exp"],
    )


def confirmed_plan_scope(identity: VerifiedIdentity | None, granted_scopes: str | None) -> bool:
    """Отмечает наличие scope только после проверки личности; это не гарантия квоты."""
    if not isinstance(identity, VerifiedIdentity) or not isinstance(granted_scopes, str):
        return False
    return _PLAN_SCOPE in set(granted_scopes.split())
