"""Meal plans: generate (Gemini), save, list, view, edit a meal, regenerate a meal, delete. Owner-scoped."""
from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import User, current_user, user_allergens
from app.api.limits import limit
from app.api.routes.analyze import error, get_nutrition
from app.core.db import get_db, jdump, jload, now_iso
from app.services import chat
from app.services import meal_planner as MP

router = APIRouter(prefix="/api/meal-plans", tags=["meal planner"])


class PlanRequest(BaseModel):
    days: Literal[1, 7] = 1
    dietary_preferences: list[str] = Field(default_factory=list, max_length=10)
    disliked_foods: list[str] = Field(default_factory=list, max_length=30)
    available_ingredients: list[str] = Field(default_factory=list, max_length=40)
    budget: Literal["low", "medium", "high"] | None = None
    meals: list[Literal["breakfast", "lunch", "dinner", "snack"]] = Field(default_factory=lambda: ["breakfast", "lunch", "dinner", "snack"])
    goals: str | None = Field(default=None, max_length=200)
    target_kcal_per_day: int | None = Field(default=None, ge=0, le=20000)  # only when the user enters one; range checked below


TARGET_MIN, TARGET_MAX = 1000, 4500
MSG_TARGET = (f"Enter a daily energy target between {TARGET_MIN} and {TARGET_MAX} kcal, or leave it empty. For a target outside "
              "this range, plan with a doctor or registered dietitian.")


def nutrition_lookup(name: str) -> dict | None:
    """The project's verified per-100 g reference record for a food name (USDA FoodData Central), or None."""
    return get_nutrition().lookup(name)


class Ingredient(BaseModel):
    item: str = Field(min_length=1, max_length=80)
    grams: float | None = Field(default=None, ge=0, le=5000)


class MealEdit(BaseModel):
    day: int = Field(ge=1, le=7)
    meal: Literal["breakfast", "lunch", "dinner", "snack"]
    name: str = Field(min_length=1, max_length=120)
    ingredients: list[Ingredient] = Field(max_length=20)


class MealRef(BaseModel):
    day: int = Field(ge=1, le=7)
    meal: Literal["breakfast", "lunch", "dinner", "snack"]


def _clean(xs: list[str]) -> list[str]:
    return [" ".join(x.split())[:60] for x in xs if x and x.strip()]


def _row(r: sqlite3.Row, full: bool = True) -> dict:
    d = {"id": r["id"], "title": r["title"], "created_at": r["created_at"], "updated_at": r["updated_at"], "request": jload(r["request"], {})}
    if full:
        d["plan"] = jload(r["plan"], {})
    return d


def _own(conn: sqlite3.Connection, user_id: int, plan_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM meal_plans WHERE id = ? AND user_id = ?", (plan_id, user_id)).fetchone()


@router.post("", status_code=201, dependencies=[Depends(limit("chat"))])  # one Gemini request
def create_plan(body: PlanRequest, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    if body.target_kcal_per_day is not None and not TARGET_MIN <= body.target_kcal_per_day <= TARGET_MAX:
        return error("TARGET_OUT_OF_RANGE", MSG_TARGET, 422)
    req = body.model_dump()
    for k in ("dietary_preferences", "disliked_foods", "available_ingredients"):
        req[k] = _clean(req[k])
    req["dietary_preferences"] = req["dietary_preferences"] or user["dietary_preferences"]
    req["disliked_foods"] = list(dict.fromkeys(req["disliked_foods"] + user["disliked_foods"]))
    prefs = user_allergens(conn, user.id)
    try:
        plan = MP.generate(req, prefs, nutrition_lookup)
    except chat.ChatError as exc:
        return error(exc.code, exc.message if exc.code != "CHAT_NOT_CONFIGURED" else
                     "The meal planner uses Gemini. Add GEMINI_API_KEY to backend/.env and restart the server.", exc.status)
    title = (f"{body.days}-day plan" + (f" ({', '.join(req['dietary_preferences'][:2])})" if req["dietary_preferences"] else "")
             + (f", {body.target_kcal_per_day} kcal/day" if body.target_kcal_per_day else ""))
    now = now_iso()
    with conn:
        cur = conn.execute("INSERT INTO meal_plans (user_id, title, request, plan, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                           (user.id, title, jdump(req), jdump(plan), now, now))
    return {"success": True, "plan": _row(_own(conn, user.id, cur.lastrowid))}


@router.get("")
def list_plans(user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute("SELECT * FROM meal_plans WHERE user_id = ? ORDER BY created_at DESC LIMIT 50", (user.id,)).fetchall()
    return {"success": True, "items": [_row(r, full=False) for r in rows]}


@router.get("/{plan_id}")
def get_plan(plan_id: int, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    r = _own(conn, user.id, plan_id)
    return {"success": True, "plan": _row(r)} if r else error("NOT_FOUND", "Meal plan not found.", 404)


def _save(conn: sqlite3.Connection, user: User, r: sqlite3.Row, plan: dict) -> dict:
    MP.finalise(plan, user_allergens(conn, user.id), jload(r["request"], {}).get("disliked_foods", []), nutrition_lookup)
    with conn:
        conn.execute("UPDATE meal_plans SET plan = ?, updated_at = ? WHERE id = ? AND user_id = ?", (jdump(plan), now_iso(), r["id"], user.id))
    return {"success": True, "plan": _row(_own(conn, user.id, r["id"]))}


def _find(plan: dict, day: int, meal: str) -> tuple[dict, int] | None:
    for d in plan.get("days", []):
        if d["day"] == day:
            for i, m in enumerate(d["meals"]):
                if m["meal"] == meal:
                    return d, i
            return d, -1
    return None


@router.put("/{plan_id}/meal")
def edit_meal(plan_id: int, body: MealEdit, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    r = _own(conn, user.id, plan_id)
    if r is None:
        return error("NOT_FOUND", "Meal plan not found.", 404)
    plan = jload(r["plan"], {})
    found = _find(plan, body.day, body.meal)
    if found is None:
        return error("NOT_FOUND", "That day is not in this plan.", 404)
    d, idx = found
    meal = {"meal": body.meal, "name": " ".join(body.name.split()), "ingredients": [i.model_dump() for i in body.ingredients],
            "estimated_nutrition": {k: None for k in ("energy_kcal", "protein_g", "carbohydrate_g", "total_fat_g", "dietary_fibre_g")},
            "nutrition_label": "Edited by you; nutrition not estimated", "substitutions": [], "prep_note": "", "edited_by_user": True}
    if idx >= 0:
        d["meals"][idx] = meal
    else:
        d["meals"].append(meal)
    return _save(conn, user, r, plan)


@router.post("/{plan_id}/regenerate", dependencies=[Depends(limit("chat"))])
def regenerate(plan_id: int, body: MealRef, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    r = _own(conn, user.id, plan_id)
    if r is None:
        return error("NOT_FOUND", "Meal plan not found.", 404)
    plan = jload(r["plan"], {})
    found = _find(plan, body.day, body.meal)
    if found is None or found[1] < 0:
        return error("NOT_FOUND", "That meal is not in this plan.", 404)
    d, idx = found
    try:
        d["meals"][idx] = MP.regenerate_meal(jload(r["request"], {}), user_allergens(conn, user.id), body.day, body.meal, d["meals"][idx]["name"])
    except chat.ChatError as exc:
        return error(exc.code, exc.message, exc.status)
    return _save(conn, user, r, plan)


@router.delete("/{plan_id}")
def delete_plan(plan_id: int, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    with conn:
        n = conn.execute("DELETE FROM meal_plans WHERE id = ? AND user_id = ?", (plan_id, user.id)).rowcount
    return {"success": True} if n else error("NOT_FOUND", "Meal plan not found.", 404)
