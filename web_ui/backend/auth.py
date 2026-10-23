"""Password hashing helpers for the Web UI."""

import base64
import binascii
import re
import time
from collections import deque
from threading import Lock

from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Return an Argon2id hash suitable for storage in the secrets file."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password must not be empty")
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, candidate: str) -> bool:
    """Verify a password without exposing malformed or mismatched hashes."""
    if not isinstance(password_hash, str) or not isinstance(candidate, str):
        return False
    try:
        return _PASSWORD_HASHER.verify(password_hash, candidate)
    except (InvalidHashError, VerificationError):
        return False


def is_password_hash(value: str) -> bool:
    """Return whether value is a complete, valid Argon2id PHC hash."""
    if not isinstance(value, str) or len(value) > 512:
        return False
    try:
        parameters = extract_parameters(value)
        parts = value.split("$")
        if (
            len(parts) != 6
            or parts[0] != ""
            or parts[1] != "argon2id"
            or parts[2] != "v=19"
            or not re.fullmatch(r"m=\d+,t=\d+,p=\d+", parts[3])
            or not re.fullmatch(r"[A-Za-z0-9+/]+", parts[4])
            or not re.fullmatch(r"[A-Za-z0-9+/]+", parts[5])
        ):
            return False
        salt = base64.b64decode(parts[4] + "=" * (-len(parts[4]) % 4), validate=True)
        digest = base64.b64decode(parts[5] + "=" * (-len(parts[5]) % 4), validate=True)
    except (InvalidHashError, binascii.Error, IndexError, TypeError, ValueError):
        return False
    return (
        parameters.type == Type.ID
        and parameters.version == 19
        and parameters.salt_len == _PASSWORD_HASHER.salt_len
        and parameters.hash_len == _PASSWORD_HASHER.hash_len
        and parameters.time_cost > 0
        and parameters.time_cost <= 10
        and parameters.memory_cost > 0
        and parameters.memory_cost <= 262144
        and parameters.parallelism > 0
        and parameters.parallelism <= 8
        and len(salt) == parameters.salt_len
        and base64.b64encode(salt).decode("ascii").rstrip("=") == parts[4]
        and len(digest) == parameters.hash_len
        and base64.b64encode(digest).decode("ascii").rstrip("=") == parts[5]
    )


class AuthRateLimiter:
    """Bound failed credential checks per client before expensive hash verification."""

    def __init__(self, max_attempts=5, window_seconds=60, max_clients=1024, clock=None):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self.clock = clock or time.monotonic
        self._failures = {}
        self._lock = Lock()

    def _prune(self, now):
        cutoff = now - self.window_seconds
        for client, attempts in list(self._failures.items()):
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts:
                del self._failures[client]

    def is_limited(self, client):
        now = self.clock()
        with self._lock:
            self._prune(now)
            return len(self._failures.get(client, ())) >= self.max_attempts

    def record_failure(self, client):
        now = self.clock()
        with self._lock:
            self._prune(now)
            if client not in self._failures and len(self._failures) >= self.max_clients:
                self._failures.pop(next(iter(self._failures)))
            self._failures.setdefault(client, deque()).append(now)

    def reset(self, client):
        with self._lock:
            self._failures.pop(client, None)
