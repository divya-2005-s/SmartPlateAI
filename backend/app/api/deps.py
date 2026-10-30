"""Authentication dependencies. The user is always taken from the session token, never from client-supplied IDs."""
from __future__ import annotations

import sqlite3

from fastapi import Depends, HTTPException, Request

from app.core.db import get_db, jload, now_iso
from app.core.security import user_for_token
from app.services import auth as auth_store


class User(dict):
    @property
    def id(self) -> int:
        return self["id"]


def _token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        return tok or None
    return None


def _to_user(row: sqlite3.Row) -> User:
    return User(id=row["id"], email=row["email"], name=row["name"], birth_year=row["birth_year"],
                dietary_preferences=jload(row["dietary_preferences"], []), disliked_foods=jload(row["disliked_foods"], []),
                created_at=row["created_at"])


def _cookie_user(request: Request, conn: sqlite3.Connection) -> sqlite3.Row | None:
    token = request.cookies.get("smartplate_session")
    auth_user = auth_store.get_session_user(token) if token else None
    if auth_user is None:
        return None
    row = conn.execute("SELECT * FROM users WHERE email = ?", (auth_user["email"],)).fetchone()
    if row is None:
        email = auth_user["email"]
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (email, email.partition("@")[0] or "SmartPlate user",
                 f"cookie-session${auth_user['id']}", now_iso()),
            )
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return row


def current_user(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> User:
    tok = _token(request)
    row = user_for_token(conn, tok) if tok else None
    if not tok:
        row = _cookie_user(request, conn)
    if row is None:
        raise HTTPException(status_code=401, detail={"success": False, "error_code": "NOT_AUTHENTICATED",
                                                     "message": "Please sign in to use this feature."})
    return _to_user(row)


def optional_user(request: Request) -> User | None:
    """Used by public endpoints that add personal information (e.g. allergen alerts) when the user is signed in."""
    from app.core.db import connect  # noqa: PLC0415
    conn = connect()
    try:
        tok = _token(request)
        row = user_for_token(conn, tok) if tok else _cookie_user(request, conn)
        return _to_user(row) if row else None
    finally:
        conn.close()


def user_allergens(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    return [{"allergen": r["allergen"], "severity": r["severity"]}
            for r in conn.execute("SELECT allergen, severity FROM allergen_prefs WHERE user_id = ? ORDER BY allergen", (user_id,))]
