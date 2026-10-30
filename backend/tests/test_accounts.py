"""Accounts, sessions, profile, allergen preferences, history, food log and owner scoping (real SQLite, temp file)."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import connect, migrate
from app.core.security import hash_password, verify_password
from app.main import app
from app.services import analysis_store

client = TestClient(app)


def signup(name="Asha Rao", email=None, password="correct-horse-1"):
    email = email or f"user_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/signup", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()["token"], email


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_password_hashing():
    h = hash_password("secret-pass", iterations=1000)
    assert verify_password("secret-pass", h) and not verify_password("wrong", h) and "secret-pass" not in h


def test_migrations_are_idempotent():
    conn = connect()
    assert migrate(conn) == []  # already applied, nothing re-run
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "sessions", "scans", "food_log", "meal_plans", "allergen_prefs", "corrections", "http_cache"} <= tables


def test_signup_login_me_logout():
    tok, email = signup()
    assert client.get("/api/auth/me", headers=auth(tok)).json()["user"]["email"] == email
    assert client.post("/api/auth/signup", json={"name": "X Y", "email": email.upper(), "password": "another-pass"}).json()["error_code"] == "EMAIL_TAKEN"
    bad = client.post("/api/auth/login", json={"email": email, "password": "nope"})
    assert bad.status_code == 401 and bad.json()["error_code"] == "INVALID_CREDENTIALS"
    tok2 = client.post("/api/auth/login", json={"email": email, "password": "correct-horse-1"}).json()["token"]
    assert client.post("/api/auth/logout", headers=auth(tok2)).json()["success"]
    r = client.get("/api/auth/me", headers=auth(tok2))
    assert r.status_code == 401 and r.json()["error_code"] == "NOT_AUTHENTICATED"
    assert client.get("/api/auth/me", headers=auth(tok)).status_code == 200  # other session still valid


def test_validation_messages():
    r = client.post("/api/auth/signup", json={"name": "A B", "email": "not-an-email", "password": "12345678"})
    assert r.status_code == 422 and r.json()["error_code"] == "INVALID_INPUT" and "email" in r.json()["message"]
    assert client.post("/api/auth/signup", json={"name": "A B", "email": "a@b.co", "password": "short"}).status_code == 422


def test_login_rate_limit():
    _, email = signup()
    for _ in range(8):
        client.post("/api/auth/login", json={"email": email, "password": "bad"})
    assert client.post("/api/auth/login", json={"email": email, "password": "correct-horse-1"}).json()["error_code"] == "TOO_MANY_ATTEMPTS"


def test_profile_and_password_change():
    tok, email = signup()
    u = client.patch("/api/profile", headers=auth(tok), json={"birth_year": 2002, "dietary_preferences": ["vegetarian", "Vegetarian"],
                                                              "disliked_foods": ["okra"]}).json()["user"]
    assert u["birth_year"] == 2002 and u["dietary_preferences"] == ["vegetarian"] and u["disliked_foods"] == ["okra"]
    assert client.post("/api/profile/password", headers=auth(tok), json={"current_password": "x", "new_password": "newpass-123"}).status_code == 401
    assert client.post("/api/profile/password", headers=auth(tok), json={"current_password": "correct-horse-1", "new_password": "newpass-123"}).json()["success"]
    assert client.post("/api/auth/login", json={"email": email, "password": "newpass-123"}).status_code == 200


def test_allergen_preferences_are_private():
    a, _ = signup()
    b, _ = signup()
    r = client.put("/api/allergens/preferences", headers=auth(a), json={"allergens": [{"allergen": "peanut", "severity": "severe"}, {"allergen": "milk"}]})
    assert [x["allergen"] for x in r.json()["allergens"]] == ["milk", "peanut"]
    assert client.get("/api/allergens/preferences", headers=auth(b)).json()["allergens"] == []
    assert client.put("/api/allergens/preferences", headers=auth(a), json={"allergens": [{"allergen": "unicorn"}]}).json()["error_code"] == "INVALID_ALLERGEN"
    assert client.get("/api/allergens/preferences").status_code == 401


def fresh_result(food="Apple", per100=52.0):
    return {"success": True, "prediction": {"food": food, "class_id": 0, "confidence": 0.93, "margin": 0.8, "top_k": []},
            "freshness": {"status": "fresh", "confidence": 0.9, "message": "Looks fresh"},
            "nutrition": {"basis": "per 100 g (USDA)", "source_fdc_id": 1, "serving_grams": None, "not_available": ["Iron"],
                          "nutrients": [{"key": "energy_kcal", "label": "Energy", "unit": "kcal", "per_100g": per100, "per_serving": None},
                                        {"key": "protein_g", "label": "Protein", "unit": "g", "per_100g": 0.3, "per_serving": None},
                                        {"key": "sodium_mg", "label": "Sodium", "unit": "mg", "per_100g": None, "per_serving": None}]},
            "precautions": [{"text": "Wash under running water"}]}


def test_history_save_dedupe_scope_and_delete():
    a, _ = signup()
    b, _ = signup()
    aid = analysis_store.put("fresh", fresh_result())
    r1 = client.post("/api/history", headers=auth(a), json={"analysis_id": aid})
    r2 = client.post("/api/history", headers=auth(a), json={"analysis_id": aid})
    assert r1.status_code == 201 and not r1.json()["duplicate"] and r2.json()["duplicate"]
    sid = r1.json()["scan"]["id"]
    s = r1.json()["scan"]["summary"]
    assert s["identity"]["source"] == "model" and s["nutrition"]["per_100g"]["energy_kcal"] == 52.0
    assert s["nutrition"]["per_100g"]["sodium_mg"] is None  # missing stays missing
    assert client.get("/api/history", headers=auth(a)).json()["total"] == 1
    assert client.get("/api/history", headers=auth(b)).json()["total"] == 0
    assert client.get(f"/api/history/{sid}", headers=auth(b)).status_code == 404
    assert client.delete(f"/api/history/{sid}", headers=auth(b)).status_code == 404
    assert client.get("/api/history?q=app&kind=fresh", headers=auth(a)).json()["total"] == 1
    assert client.get("/api/history?q=zzz", headers=auth(a)).json()["total"] == 0
    assert client.post("/api/history", headers=auth(a), json={"analysis_id": "doesnotexist1"}).json()["error_code"] == "ANALYSIS_EXPIRED"
    assert client.delete(f"/api/history/{sid}", headers=auth(a)).json()["success"]


def test_food_log_totals_missing_values_and_scaling():
    a, _ = signup()
    aid = analysis_store.put("fresh", fresh_result())
    sid = client.post("/api/history", headers=auth(a), json={"analysis_id": aid}).json()["scan"]["id"]
    day = "2026-10-12"
    e1 = client.post("/api/nutrition/entries", headers=auth(a), json={"logged_on": day, "meal": "breakfast", "scan_id": sid, "grams": 200,
                                                                     "client_ref": "r1"}).json()
    assert e1["entry"]["amounts"]["energy_kcal"] == pytest.approx(104.0)
    dup = client.post("/api/nutrition/entries", headers=auth(a), json={"logged_on": day, "scan_id": sid, "grams": 200, "client_ref": "r1"}).json()
    assert dup["duplicate"]
    client.post("/api/nutrition/entries", headers=auth(a), json={"logged_on": day, "meal": "lunch", "name": "Home dal",
                                                                "nutrients": {"energy_kcal": 300, "sodium_mg": 400}})
    t = {x["key"]: x for x in client.get(f"/api/nutrition/day?day={day}", headers=auth(a)).json()["totals"]}
    assert t["energy_kcal"]["total"] == pytest.approx(404.0) and t["energy_kcal"]["complete"]
    assert t["sodium_mg"]["total"] == 400 and t["sodium_mg"]["entries_missing"] == 1 and not t["sodium_mg"]["complete"]
    assert t["dietary_fibre_g"]["total"] is None  # nothing known -> not zero
    eid = e1["entry"]["id"]
    patched = client.patch(f"/api/nutrition/entries/{eid}", headers=auth(a), json={"grams": 100}).json()
    assert patched["entry"]["amounts"]["energy_kcal"] == pytest.approx(52.0)
    assert client.patch(f"/api/nutrition/entries/{eid}", headers=auth(a), json={"nutrients": {"energy_kcal": 1}}).json()["error_code"] == "NOT_EDITABLE"
    week = client.get(f"/api/nutrition/week?end={day}", headers=auth(a)).json()
    assert len(week["days"]) == 7 and week["days"][-1]["entry_count"] == 2
    assert client.post("/api/nutrition/entries", headers=auth(a), json={"logged_on": day, "name": "x", "nutrients": {"bogus": 1}}).status_code == 422
    b, _ = signup()
    assert client.delete(f"/api/nutrition/entries/{eid}", headers=auth(b)).status_code == 404
    assert client.post("/api/nutrition/entries", headers=auth(b), json={"logged_on": day, "scan_id": sid, "grams": 10}).status_code == 404


def test_packaged_scan_with_unknown_basis_cannot_be_scaled():
    a, _ = signup()
    res = {"success": True, "product": {"id": "1", "name": "Biscuit", "brand": "B", "category": None, "ingredients_text": None, "allergens_text": None,
                                        "additive_codes": [], "nutrition": {"basis_known": False, "nutrients": [], "source": "dataset"}},
           "label": {"nutrition": {"basis": "unknown", "values": {}}, "allergens": []}, "match": {"status": "matched", "confidence": 0.9},
           "additives": [], "precautions": []}
    sid = client.post("/api/history", headers=auth(a), json={"analysis_id": analysis_store.put("packaged", res)}).json()["scan"]["id"]
    r = client.post("/api/nutrition/entries", headers=auth(a), json={"logged_on": "2026-10-12", "scan_id": sid, "grams": 30})
    assert r.json()["error_code"] == "BASIS_UNKNOWN"


def test_corrections_queue():
    a, _ = signup()
    r = client.post("/api/corrections", headers=auth(a), json={"predicted": "Taco", "corrected": "Burrito"})
    assert r.json()["status"] == "pending_review"
    assert client.post("/api/corrections", headers=auth(a), json={"predicted": "Taco"}).status_code == 422
    assert len(client.get("/api/corrections", headers=auth(a)).json()["items"]) == 1


def test_delete_account_removes_data():
    a, email = signup()
    client.post("/api/history", headers=auth(a), json={"analysis_id": analysis_store.put("fresh", fresh_result())})
    assert client.post("/api/profile/delete", headers=auth(a), json={"password": "wrong"}).status_code == 401
    assert client.post("/api/profile/delete", headers=auth(a), json={"password": "correct-horse-1"}).json()["success"]
    assert client.post("/api/auth/login", json={"email": email, "password": "correct-horse-1"}).status_code == 401
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM scans s LEFT JOIN users u ON u.id = s.user_id WHERE u.id IS NULL").fetchone()[0] == 0
