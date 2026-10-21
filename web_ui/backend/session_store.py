"""Persistent, revocable browser sessions and login throttling."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SESSION_MAX_AGE = 12 * 60 * 60
LOGIN_WINDOW = 15 * 60
LOGIN_LOCKOUT = 15 * 60
LOGIN_FAILURE_LIMIT = 5


@dataclass(frozen=True)
class StoredSession:
    username: str
    csrf_hash: str
    expires_at: float


class SessionStore:
    def __init__(self, path: str | Path, secret: bytes):
        self.path = Path(path)
        self.secret = secret
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    csrf_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    credential_version TEXT
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    identity_hash TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    window_start REAL NOT NULL,
                    locked_until REAL NOT NULL
                );
                """)
            session_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(sessions)")
            }
            if "credential_version" not in session_columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN credential_version TEXT")
        self.path.chmod(0o600)

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _digest(self, purpose: str, value: str) -> str:
        message = f"{purpose}:{value}".encode("utf-8")
        return hmac.new(self.secret, message, hashlib.sha256).hexdigest()

    def create(
        self,
        username: str,
        max_age: int = SESSION_MAX_AGE,
        credential_version: str | None = None,
    ) -> tuple[str, str]:
        now = time.time()
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            connection.execute(
                """INSERT INTO sessions
                   (token_hash, username, csrf_hash, created_at, expires_at, credential_version)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    self._digest("session", token),
                    username,
                    self._digest("csrf", csrf_token),
                    now,
                    now + max_age,
                    credential_version,
                ),
            )
        return token, csrf_token

    def get(
        self,
        token: str,
        now: float | None = None,
        credential_version: str | None = None,
    ) -> StoredSession | None:
        current_time = time.time() if now is None else now
        token_hash = self._digest("session", token)
        with self._connect() as connection:
            row = connection.execute(
                """SELECT username, csrf_hash, expires_at, credential_version
                   FROM sessions WHERE token_hash = ?""",
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] <= current_time:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
            if credential_version is not None and not hmac.compare_digest(
                row["credential_version"] or "", credential_version
            ):
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
        return StoredSession(row["username"], row["csrf_hash"], row["expires_at"])

    def verify_csrf(self, token: str, csrf_token: str) -> bool:
        session = self.get(token)
        if session is None:
            return False
        supplied_hash = self._digest("csrf", csrf_token)
        return hmac.compare_digest(session.csrf_hash, supplied_hash)

    def revoke(self, token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (self._digest("session", token),)
            )

    def is_login_allowed(self, identity: str, now: float | None = None) -> bool:
        current_time = time.time() if now is None else now
        identity_hash = self._digest("login", identity)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT failures, window_start, locked_until FROM login_attempts "
                "WHERE identity_hash = ?",
                (identity_hash,),
            ).fetchone()
            if row is None:
                return True
            if row["locked_until"] > current_time:
                return False
            if current_time - row["window_start"] >= LOGIN_WINDOW:
                connection.execute(
                    "DELETE FROM login_attempts WHERE identity_hash = ?", (identity_hash,)
                )
            return True

    def record_login_failure(self, identity: str, now: float | None = None) -> None:
        current_time = time.time() if now is None else now
        identity_hash = self._digest("login", identity)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT failures, window_start FROM login_attempts WHERE identity_hash = ?",
                (identity_hash,),
            ).fetchone()
            if row is None or current_time - row["window_start"] >= LOGIN_WINDOW:
                failures = 1
                window_start = current_time
            else:
                failures = row["failures"] + 1
                window_start = row["window_start"]
            locked_until = current_time + LOGIN_LOCKOUT if failures >= LOGIN_FAILURE_LIMIT else 0
            connection.execute(
                "INSERT OR REPLACE INTO login_attempts VALUES (?, ?, ?, ?)",
                (identity_hash, failures, window_start, locked_until),
            )

    def clear_login_failures(self, identity: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM login_attempts WHERE identity_hash = ?",
                (self._digest("login", identity),),
            )
