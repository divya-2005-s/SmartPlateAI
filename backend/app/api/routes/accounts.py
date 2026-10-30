"""Account profile and allergen preference endpoints shared by cookie and bearer sessions."""
from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import User, current_user, user_allergens
from app.api.routes.analyze import error
from app.core.db import get_db, jdump, jload
from app.core.security import hash_password, revoke, token_hash, verify_password
from app.services import allergens as allergen_service
from app.services import auth as auth_store

router = APIRouter(prefix="/api", tags=["account"])


class ProfileIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    dietary_preferences: list[str] | None = Field(default=None, max_length=20)
    disliked_foods: list[str] | None = Field(default=None, max_length=50)


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class DeleteIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class AllergenPref(BaseModel):
    allergen: str
    severity: Literal["avoid", "severe"] = "avoid"


class AllergensIn(BaseModel):
    allergens: list[AllergenPref] = Field(max_length=len(allergen_service.ALLERGENS))


def _public(user: User) -> dict:
    return {k: user[k] for k in (
        "id", "email", "name", "birth_year", "dietary_preferences", "disliked_foods", "created_at"
    )}


def _clean_list(items: list[str] | None) -> list[str] | None:
    if items is None:
        return None
    cleaned: list[str] = []
    for item in items:
        value = " ".join(item.split())[:60]
        if value and value.casefold() not in {existing.casefold() for existing in cleaned}:
            cleaned.append(value)
    return cleaned


def _is_cookie_session(request: Request) -> bool:
    return not request.headers.get("authorization", "").lower().startswith("bearer ")


@router.get("/profile")
def get_profile(user: User = Depends(current_user)):
    return {"success": True, "user": _public(user)}


@router.patch("/profile")
def update_profile(body: ProfileIn, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    fields: list[str] = []
    values: list[object] = []
    if body.name is not None:
        fields.append("name = ?")
        values.append(" ".join(body.name.split()))
    if "birth_year" in body.model_fields_set:
        fields.append("birth_year = ?")
        values.append(body.birth_year)
    for key in ("dietary_preferences", "disliked_foods"):
        cleaned = _clean_list(getattr(body, key))
        if cleaned is not None:
            fields.append(f"{key} = ?")
            values.append(jdump(cleaned))
    if fields:
        with conn:
            conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", (*values, user.id))  # fixed column names
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user.id,)).fetchone()
    from app.api.deps import _to_user
    return {"success": True, "user": _public(_to_user(row))}


@router.post("/profile/password")
def change_password(
    body: PasswordIn,
    request: Request,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    if _is_cookie_session(request):
        cookie_token = request.cookies.get("smartplate_session")
        if not auth_store.change_password(user["email"], body.current_password, body.new_password, cookie_token):
            return error("INVALID_CREDENTIALS", "Your current password is incorrect.", 401)
        new_hash = hash_password(body.new_password)
        with conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user.id))
    else:
        if not verify_password(body.current_password, row["password_hash"]):
            return error("INVALID_CREDENTIALS", "Your current password is incorrect.", 401)
        token = request.headers["authorization"][7:].strip()
        with conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.new_password), user.id))
            conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user.id, token_hash(token)))
    return {"success": True, "message": "Password changed. Other devices were signed out."}


@router.post("/profile/delete")
def delete_account(
    body: DeleteIn,
    request: Request,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    if _is_cookie_session(request):
        if auth_store.authenticate(user["email"], body.password) is None:
            return error("INVALID_CREDENTIALS", "Your password is incorrect.", 401)
        auth_store.delete_user(user["email"])
    else:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
        if not verify_password(body.password, row["password_hash"]):
            return error("INVALID_CREDENTIALS", "Your password is incorrect.", 401)
    with conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user.id,))
    return {"success": True}


@router.get("/allergens/options")
def allergen_options():
    return {
        "success": True,
        "allergens": [{"key": key, "name": value[0]} for key, value in allergen_service.ALLERGENS.items()],
        "severities": list(allergen_service.SEVERITIES),
    }


@router.get("/allergens/preferences")
def get_allergen_preferences(user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return {"success": True, "allergens": user_allergens(conn, user.id)}


@router.put("/allergens/preferences")
def put_allergen_preferences(
    body: AllergensIn,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    invalid = [item.allergen for item in body.allergens if item.allergen not in allergen_service.ALLERGENS]
    if invalid:
        return error("INVALID_ALLERGEN", f"Unknown allergen(s): {', '.join(invalid)}.", 422)
    unique = {item.allergen: item for item in body.allergens}
    with conn:
        conn.execute("DELETE FROM allergen_prefs WHERE user_id = ?", (user.id,))
        conn.executemany(
            "INSERT INTO allergen_prefs (user_id, allergen, severity) VALUES (?, ?, ?)",
            [(user.id, item.allergen, item.severity) for item in unique.values()],
        )
    return {"success": True, "allergens": user_allergens(conn, user.id)}
