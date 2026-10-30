"""SQLite-backed account and opaque session storage."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BACKEND_DIR = Path(__file__).resolve().parents[2]
# AUTH_DATABASE_PATH lets a server keep accounts on persistent storage (e.g. a mounted volume); default unchanged.
DB_PATH = Path(os.environ.get("AUTH_DATABASE_PATH") or BACKEND_DIR / "data" / "smartplate_users.db")
PASSWORD_ITERATIONS = 600_000
_DUMMY_SALT = b"smartplate-invalid-account-check"


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
        """
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256" or int(rounds) != PASSWORD_ITERATIONS:
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PASSWORD_ITERATIONS)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_user(email: str, password: str) -> dict | None:
    now = int(time.time())
    encoded = _hash_password(password)
    try:
        with _connection() as conn:
            cur = conn.execute("INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
                               (email, encoded, now))
            return {"id": cur.lastrowid, "email": email}
    except sqlite3.IntegrityError:
        return None


def authenticate(email: str, password: str) -> dict | None:
    with _connection() as conn:
        row = conn.execute("SELECT id, email, password_hash FROM users WHERE email = ?", (email,)).fetchone()
    if row is None:
        hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _DUMMY_SALT, PASSWORD_ITERATIONS)
        return None
    if not _verify_password(password, row["password_hash"]):
        return None
    return {"id": row["id"], "email": row["email"]}


def create_session(user_id: int, lifetime_seconds: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with _connection() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                     (hashlib.sha256(token.encode("ascii")).hexdigest(), user_id, now + lifetime_seconds, now))
    return token


def get_session_user(token: str) -> dict | None:
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    now = int(time.time())
    with _connection() as conn:
        row = conn.execute(
            "SELECT users.id, users.email, sessions.expires_at FROM sessions "
            "JOIN users ON users.id = sessions.user_id WHERE sessions.token_hash = ?", (token_hash,)
        ).fetchone()
        if row is not None and row["expires_at"] <= now:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            return None
        return {"id": row["id"], "email": row["email"]} if row else None


def delete_session(token: str) -> None:
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    with _connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def change_password(email: str, current_password: str, new_password: str, current_token: str | None = None) -> bool:
    with _connection() as conn:
        row = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
        if row is None or not _verify_password(current_password, row["password_hash"]):
            return False
        digest = hashlib.sha256(current_token.encode("ascii", errors="ignore")).hexdigest() if current_token else None
        with conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_hash_password(new_password), row["id"]))
            if digest:
                conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (row["id"], digest))
            else:
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
    return True


def delete_user(email: str) -> None:
    with _connection() as conn:
        conn.execute("DELETE FROM users WHERE email = ?", (email,))