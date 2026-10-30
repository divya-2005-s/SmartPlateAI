"""Signup, login, current-user, and logout endpoints."""
from __future__ import annotations

import os
import re
import sqlite3

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.core.config import Settings, get_settings
from app.core.db import get_db, jload, now_iso
from app.core.security import create_session as create_feature_session
from app.core.security import hash_password, login_limiter, revoke, user_for_token, verify_password
from app.api.limits import limit
from app.services import auth as auth_store

router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE_NAME = "smartplate_session"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().casefold()
        if not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("Enter a valid email address.")
        return value


class SignupRequest(Credentials):
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, min_length=2, max_length=80)


class UserResponse(BaseModel):
    id: int
    email: str


def _cookie_options(settings: Settings) -> tuple[bool, str, int]:
    secure_value = os.getenv("AUTH_COOKIE_SECURE")
    production = settings.environment.strip().lower() in {"production", "prod"}
    secure = (secure_value.strip().lower() in {"1", "true", "yes"} if secure_value is not None else production)
    if production and not secure:
        raise RuntimeError("AUTH_COOKIE_SECURE cannot be disabled in production")
    same_site = os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
    if same_site not in {"lax", "strict", "none"}:
        raise RuntimeError("AUTH_COOKIE_SAMESITE must be lax, strict, or none")
    if same_site == "none" and not secure:
        raise RuntimeError("AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=true")
    try:
        session_days = int(os.getenv("AUTH_SESSION_DAYS", "30"))
    except ValueError as exc:
        raise RuntimeError("AUTH_SESSION_DAYS must be a positive integer") from exc
    if session_days < 1:
        raise RuntimeError("AUTH_SESSION_DAYS must be a positive integer")
    return secure, same_site, session_days * 24 * 60 * 60


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    secure, same_site, lifetime = _cookie_options(settings)
    response.set_cookie(COOKIE_NAME, token, max_age=lifetime, httponly=True, secure=secure,
                        samesite=same_site, path="/")


def _user(user: dict) -> dict:
    return {"id": int(user["id"]), "email": user["email"]}


@router.post("/signup", status_code=201, dependencies=[Depends(limit("signup"))])
def signup(payload: SignupRequest, response: Response,
           settings: Settings = Depends(get_settings),
           conn: sqlite3.Connection = Depends(get_db)):
    if payload.name is not None:
        existing = conn.execute("SELECT 1 FROM users WHERE email = ?", (payload.email,)).fetchone()
        if existing:
            response.status_code = 409
            return {"success": False, "error_code": "EMAIL_TAKEN",
                    "message": "An account with this email already exists. Sign in instead."}
        now = now_iso()
        with conn:
            cur = conn.execute(
                "INSERT INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (payload.email, " ".join(payload.name.split()), hash_password(payload.password), now),
            )
        token, expires = create_feature_session(conn, cur.lastrowid)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {
            "success": True,
            "token": token,
            "expires_at": expires,
            "user": {
                "id": row["id"],
                "email": row["email"],
                "name": row["name"],
                "birth_year": row["birth_year"],
                "dietary_preferences": jload(row["dietary_preferences"], []),
                "disliked_foods": jload(row["disliked_foods"], []),
                "created_at": row["created_at"],
            },
        }
    existing_feature_user = conn.execute("SELECT 1 FROM users WHERE email = ?", (payload.email,)).fetchone()
    if existing_feature_user:
        response.status_code = 409
        return {"success": False, "error_code": "EMAIL_ALREADY_REGISTERED",
                "message": "An account with this email already exists. Sign in instead."}
    user = auth_store.create_user(payload.email, payload.password)
    if user is None:
        response.status_code = 409
        return {"success": False, "error_code": "EMAIL_ALREADY_REGISTERED",
            "message": "An account with this email already exists."}
    token = auth_store.create_session(user["id"], _cookie_options(settings)[2])
    _set_session_cookie(response, token, settings)
    return {"success": True, "user": _user(user)}


@router.post("/login", dependencies=[Depends(limit("login"))])
def login(payload: Credentials, response: Response,
          settings: Settings = Depends(get_settings),
          conn: sqlite3.Connection = Depends(get_db)):
    email = payload.email
    if login_limiter.blocked(email):
        response.status_code = 429
        return {"success": False, "error_code": "TOO_MANY_ATTEMPTS",
                "message": "Too many failed sign-in attempts. Please wait 10 minutes and try again."}
    feature_user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if feature_user is not None and not feature_user["password_hash"].startswith("cookie-session$"):
        if not verify_password(payload.password, feature_user["password_hash"]):
            login_limiter.fail(email)
            response.status_code = 401
            return {"success": False, "error_code": "INVALID_CREDENTIALS",
                    "message": "Email or password is incorrect."}
        login_limiter.reset(email)
        token, expires = create_feature_session(conn, feature_user["id"])
        return {
            "success": True,
            "token": token,
            "expires_at": expires,
            "user": {
                "id": feature_user["id"],
                "email": feature_user["email"],
                "name": feature_user["name"],
                "birth_year": feature_user["birth_year"],
                "dietary_preferences": jload(feature_user["dietary_preferences"], []),
                "disliked_foods": jload(feature_user["disliked_foods"], []),
                "created_at": feature_user["created_at"],
            },
        }
    user = auth_store.authenticate(payload.email, payload.password)
    if user is None:
        login_limiter.fail(email)
        response.status_code = 401
        return {"success": False, "error_code": "INVALID_CREDENTIALS",
                "message": "Email or password is incorrect."}
    login_limiter.reset(email)
    token = auth_store.create_session(user["id"], _cookie_options(settings)[2])
    _set_session_cookie(response, token, settings)
    return {"success": True, "user": _user(user)}


@router.get("/me")
def current_user(request: Request, conn: sqlite3.Connection = Depends(get_db),
                 session_token: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        row = user_for_token(conn, token) if token else None
        if row is None:
            raise HTTPException(status_code=401, detail={"success": False, "error_code": "NOT_AUTHENTICATED",
                                                         "message": "Please sign in to use this feature."})
        return {"success": True, "user": {
            "id": row["id"], "email": row["email"], "name": row["name"], "birth_year": row["birth_year"],
            "dietary_preferences": jload(row["dietary_preferences"], []),
            "disliked_foods": jload(row["disliked_foods"], []), "created_at": row["created_at"],
        }}
    user = auth_store.get_session_user(session_token) if session_token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return _user(user)


@router.post("/logout")
def logout(request: Request, response: Response, session_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
           settings: Settings = Depends(get_settings),
           conn: sqlite3.Connection = Depends(get_db)):
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            revoke(conn, token)
    if session_token:
        auth_store.delete_session(session_token)
    secure, same_site, _ = _cookie_options(settings)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=secure, samesite=same_site)
    return {"success": True}