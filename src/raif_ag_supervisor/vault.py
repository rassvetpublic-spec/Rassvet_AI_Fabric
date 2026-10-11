"""Vault abstraction: no secrets in checkpoints, logs or account registry.

Windows adapter intentionally deferred until native API tests are available.
"""

__version__ = "1.0.0"
from dataclasses import dataclass, field
from typing import Protocol

class CredentialVault(Protocol):
    def put(self, account_id: str, secret: str) -> None: ...
    def has(self, account_id: str) -> bool: ...
    def delete(self, account_id: str) -> None: ...

@dataclass
class InMemoryTestVault:
    """Synthetic-only vault. Never use for real accounts."""
    _values: dict[str, str] = field(default_factory=dict, repr=False)

    def put(self, account_id: str, secret: str) -> None:
        if not account_id or not isinstance(secret, str) or not secret:
            raise ValueError("invalid credential input")
        if not secret.startswith("synthetic-"):
            raise ValueError("test vault accepts synthetic credentials only")
        self._values[account_id] = secret

    def has(self, account_id: str) -> bool:
        return account_id in self._values

    def delete(self, account_id: str) -> None:
        self._values.pop(account_id, None)

    def __repr__(self) -> str:
        return "InMemoryTestVault(redacted)"
