"""Deployment mode: with SERVE_FRONTEND_DIR set, the API process also serves the built frontend from the same origin, never
lets a client-side route or a path trick shadow /api, and never serves files outside the build folder. Security headers are
always set. Uses a throw-away build folder; the app module is reloaded with the setting and restored afterwards."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def served(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>SmartPlateAI</title>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside the build folder", encoding="utf-8")
    import app.main as main
    monkeypatch.setenv("SERVE_FRONTEND_DIR", str(dist))
    reloaded = importlib.reload(main)
    yield TestClient(reloaded.app)
    monkeypatch.delenv("SERVE_FRONTEND_DIR")
    importlib.reload(main)


def test_frontend_routes_and_files_are_served(served):
    assert "SmartPlateAI" in served.get("/").text
    deep = served.get("/analyze")  # client-side route -> index.html
    assert deep.status_code == 200 and "SmartPlateAI" in deep.text and deep.headers["cache-control"] == "no-cache"
    js = served.get("/assets/index-abc123.js")
    assert js.text == "console.log(1)" and "immutable" in js.headers["cache-control"]
    assert served.get("/manifest.webmanifest").text == "{}"


def test_api_is_never_shadowed_by_the_frontend(served):
    assert served.get("/api/health").json()["status"] == "ok"
    missing = served.get("/api/does-not-exist")
    assert missing.status_code == 404 and missing.json()["success"] is False


@pytest.mark.parametrize("path", ["/../secret.txt", "/..%2Fsecret.txt", "/assets/../../secret.txt"])
def test_files_outside_the_build_folder_are_never_served(served, path):
    assert "outside the build folder" not in served.get(path).text


def test_security_headers(served):
    h = served.get("/api/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert "camera=(self)" in h["permissions-policy"] and h["referrer-policy"] == "strict-origin-when-cross-origin"


def test_without_the_setting_no_frontend_is_served():
    from app.main import app
    assert TestClient(app).get("/analyze").status_code == 404
