"""argon2id password hashing (design D1 / D12).

Parameters are configurable so a deployment can raise cost with its hardware. Passwords are never
logged here: this module receives plaintext only from the request body and returns a hash.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from argon2 import PasswordHasher as _Argon2Hasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

TIME_COST_ENV = "SMART_EDIT_ARGON2_TIME_COST"
MEMORY_COST_ENV = "SMART_EDIT_ARGON2_MEMORY_COST"
PARALLELISM_ENV = "SMART_EDIT_ARGON2_PARALLELISM"

# argon2-cffi defaults (RFC 9106 second recommended option); explicit so they are testable.
DEFAULT_TIME_COST = 3
DEFAULT_MEMORY_COST = 65536  # KiB (64 MiB)
DEFAULT_PARALLELISM = 4
DEFAULT_HASH_LEN = 32
DEFAULT_SALT_LEN = 16
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 512


@dataclass(frozen=True)
class Argon2Params:
    time_cost: int = DEFAULT_TIME_COST
    memory_cost: int = DEFAULT_MEMORY_COST
    parallelism: int = DEFAULT_PARALLELISM
    hash_len: int = DEFAULT_HASH_LEN
    salt_len: int = DEFAULT_SALT_LEN

    def validate(self) -> None:
        if self.time_cost < 1:
            raise ValueError(f"{TIME_COST_ENV} must be >= 1")
        if self.memory_cost < 8:
            raise ValueError(f"{MEMORY_COST_ENV} must be >= 8 KiB")
        if self.parallelism < 1:
            raise ValueError(f"{PARALLELISM_ENV} must be >= 1")


def params_from_env(values: dict[str, str] | None = None) -> Argon2Params:
    values = dict(os.environ if values is None else values)

    def read(key: str, default: int) -> int:
        raw = (values.get(key) or "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{key} must be an integer; got {raw!r}") from exc

    params = Argon2Params(
        time_cost=read(TIME_COST_ENV, DEFAULT_TIME_COST),
        memory_cost=read(MEMORY_COST_ENV, DEFAULT_MEMORY_COST),
        parallelism=read(PARALLELISM_ENV, DEFAULT_PARALLELISM),
    )
    params.validate()
    return params


class PasswordHasher:
    """Thin wrapper so tests can use cheap parameters without touching call sites."""

    def __init__(self, params: Argon2Params | None = None) -> None:
        self.params = params or Argon2Params()
        self.params.validate()
        self._hasher = _Argon2Hasher(
            time_cost=self.params.time_cost,
            memory_cost=self.params.memory_cost,
            parallelism=self.params.parallelism,
            hash_len=self.params.hash_len,
            salt_len=self.params.salt_len,
            type=Type.ID,
        )

    @classmethod
    def from_env(cls, values: dict[str, str] | None = None) -> "PasswordHasher":
        return cls(params_from_env(values))

    def hash(self, password: str) -> str:
        if not password:
            raise ValueError("password must not be empty")
        if len(password) > MAX_PASSWORD_LENGTH:
            raise ValueError("password is too long")
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """Return True/False; a malformed hash is a mismatch, never an exception or a log line."""
        if not password_hash or not password:
            return False
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True


__all__ = [
    "Argon2Params",
    "DEFAULT_HASH_LEN",
    "DEFAULT_MEMORY_COST",
    "DEFAULT_PARALLELISM",
    "DEFAULT_SALT_LEN",
    "DEFAULT_TIME_COST",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "PasswordHasher",
    "params_from_env",
]