import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.api.routes.auth import _cookie_options
from app.core.config import Settings
from app.main import app
from app.services import auth as auth_store


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_store, "DB_PATH", tmp_path / "data" / "test_users.db")
    with TestClient(app) as client:
        yield client


def test_signup_normalizes_email_hashes_password_and_restores_session(auth_client, tmp_path):
    response = auth_client.post("/api/auth/signup", json={"email": "  Test.User@Example.COM ", "password": "correct horse battery"})

    assert response.status_code == 201
    assert response.json() == {"success": True, "user": {"id": 1, "email": "test.user@example.com"}}
    assert "httponly" in response.headers["set-cookie"].lower()
    assert response.headers["set-cookie"].split(";")[0].startswith("smartplate_session=")
    assert auth_client.get("/api/auth/me").json() == {"id": 1, "email": "test.user@example.com"}

    with sqlite3.connect(tmp_path / "data" / "test_users.db") as conn:
        stored_email, password_hash = conn.execute("SELECT email, password_hash FROM users").fetchone()
        assert stored_email == "test.user@example.com"
        assert password_hash != "correct horse battery"
        assert password_hash.startswith("pbkdf2_sha256$600000$")


def test_duplicate_signup_is_case_insensitive(auth_client):
    auth_client.post("/api/auth/signup", json={"email": "Person@Example.com", "password": "password number one"})
    duplicate = auth_client.post("/api/auth/signup", json={"email": " person@example.COM ", "password": "password number two"})

    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "EMAIL_ALREADY_REGISTERED"


@pytest.mark.parametrize("payload", [
    {"email": "not-an-email", "password": "password number one"},
    {"email": "valid@example.com", "password": "short"},
])
def test_signup_validates_email_and_password(auth_client, payload):
    assert auth_client.post("/api/auth/signup", json=payload).status_code == 422


def test_login_rejects_invalid_credentials_safely(auth_client):
    auth_client.post("/api/auth/signup", json={"email": "user@example.com", "password": "password number one"})
    auth_client.post("/api/auth/logout")

    wrong_password = auth_client.post("/api/auth/login", json={"email": "user@example.com", "password": "different password"})
    unknown_email = auth_client.post("/api/auth/login", json={"email": "unknown@example.com", "password": "different password"})

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json()["error_code"] == "INVALID_CREDENTIALS"
    valid_login = auth_client.post("/api/auth/login", json={"email": " USER@example.com ", "password": "password number one"})
    assert valid_login.status_code == 200
    assert valid_login.json() == {"success": True, "user": {"id": 1, "email": "user@example.com"}}


def test_session_survives_new_client_and_logout_revokes_it(auth_client):
    auth_client.post("/api/auth/signup", json={"email": "persist@example.com", "password": "password number one"})
    cookie = auth_client.cookies.get("smartplate_session")

    with TestClient(app) as restarted_client:
        restarted_client.cookies.set("smartplate_session", cookie)
        assert restarted_client.get("/api/auth/me").json() == {"id": 1, "email": "persist@example.com"}
        logged_out = restarted_client.post("/api/auth/logout")
        assert logged_out.status_code == 200 and logged_out.json() == {"success": True}
        assert restarted_client.get("/api/auth/me").status_code == 401


def test_signup_requires_a_valid_email_field(auth_client):
    assert auth_client.post("/api/auth/signup", json={"email": "", "password": "password number one"}).status_code == 422


def test_cookie_settings_are_secure_for_production_and_usable_on_local_http(monkeypatch):
    for name in ("AUTH_COOKIE_SECURE", "AUTH_COOKIE_SAMESITE", "AUTH_SESSION_DAYS"):
        monkeypatch.delenv(name, raising=False)

    assert _cookie_options(Settings(environment="development")) == (False, "lax", 30 * 24 * 60 * 60)
    assert _cookie_options(Settings(environment="production")) == (True, "lax", 30 * 24 * 60 * 60)