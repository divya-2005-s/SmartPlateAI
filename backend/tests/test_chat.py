"""Chat endpoint tests. The Gemini network call is replaced; these check grounding, key handling and errors, not answer quality."""
import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from app.core.config import BACKEND_DIR, Settings
from app.main import app
from app.services import chat


@pytest.fixture
def c():
    return TestClient(app)


def test_not_configured(c, monkeypatch):
    monkeypatch.setattr(chat, "api_key", lambda: "")
    r = c.post("/api/chat", json={"message": "Is this healthy?"})
    assert r.status_code == 503 and r.json()["error_code"] == "CHAT_NOT_CONFIGURED"
    assert c.get("/api/chat/status").json()["configured"] is False


def test_reply_uses_context_and_hides_key(c, monkeypatch):
    seen = {}

    def fake_post(url, payload, key):
        seen.update(url=url, payload=payload, key=key)
        return {"candidates": [{"content": {"parts": [{"text": "Apple has 52 kcal per 100 g."}]}}]}
    monkeypatch.setattr(chat, "api_key", lambda: "SECRET-KEY")
    monkeypatch.setattr(chat, "get_settings", lambda: Settings(gemini_model="gemini-test-model"))
    monkeypatch.setattr(chat, "post_json", fake_post)
    ctx = {"kind": "fresh", "food": "Apple", "status": "recognised", "nutrition": [{"label": "Energy", "per_100g": 52, "unit": "kcal"}]}
    r = c.post("/api/chat", json={"message": "Calories?", "history": [{"role": "assistant", "content": "Hi"}], "context": ctx})
    j = r.json()
    assert r.status_code == 200 and j["reply"].startswith("Apple") and j["grounded_in_analysis"]
    system = seen["payload"]["systemInstruction"]["parts"][0]["text"]
    assert '"Apple"' in system and "Never treat missing as zero" in system
    assert seen["payload"]["contents"][0]["role"] == "model"
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test-model:generateContent"
    assert seen["payload"]["contents"][-1] == {"role": "user", "parts": [{"text": "Calories?"}]}
    assert seen["payload"]["generationConfig"] == {"temperature": 0.3, "maxOutputTokens": 1024}
    assert "SECRET-KEY" not in seen["url"] and "SECRET-KEY" not in r.text


def test_settings_load_model_and_key_from_explicit_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_MODEL=mock-model\nGEMINI_API_KEY=mock-only-key\n", encoding="utf-8")
    settings = Settings(_env_file=env_file)

    assert settings.gemini_model == "mock-model"
    assert settings.gemini_api_key == "mock-only-key"
    assert Settings.model_config["env_file"] == BACKEND_DIR / ".env"


@pytest.mark.parametrize("status,code", [(400, "CHAT_AUTH_FAILED"), (429, "CHAT_RATE_LIMITED"), (500, "CHAT_UNAVAILABLE")])
def test_http_errors(c, monkeypatch, status, code):
    def fake_post(url, payload, key):
        body = b'{"error":{"status":"INVALID_ARGUMENT","details":[{"reason":"API_KEY_INVALID"}]}}' if status == 400 else b"{}"
        raise urllib.error.HTTPError(url, status, "err", {}, io.BytesIO(body))
    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "post_json", fake_post)
    r = c.post("/api/chat", json={"message": "hi"})
    assert r.json()["error_code"] == code


def test_gemini_503_is_reported_as_transient_provider_error(c, monkeypatch):
    def fake_post(url, payload, key):
        body = json.dumps({"error": {"message": "This model is currently experiencing high demand.", "status": "UNAVAILABLE"}}).encode()
        raise urllib.error.HTTPError(url, 503, "err", {}, io.BytesIO(body))

    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "post_json", fake_post)
    response = c.post("/api/chat", json={"message": "hi"})

    assert response.status_code == 503
    assert response.json()["error_code"] == "CHAT_UNAVAILABLE"
    assert "high demand" in response.json()["message"].lower()


def test_model_not_found_includes_redacted_google_diagnostic(c, monkeypatch, caplog):
    secret = "test-secret-api-key"
    google_message = f"This model models/gemini-2.5-flash is no longer available to new users. Use models/gemini-next; credential={secret}"

    def fake_post(url, payload, key):
        body = json.dumps({"error": {"code": 404, "message": google_message, "status": "NOT_FOUND"}}).encode()
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(body))

    monkeypatch.setattr(chat, "api_key", lambda: secret)
    monkeypatch.setattr(chat, "post_json", fake_post)
    response = c.post("/api/chat", json={"message": "hi"})

    assert response.status_code == 502
    assert response.json()["error_code"] == "CHAT_MODEL_UNAVAILABLE"
    assert "Set GEMINI_MODEL" in response.json()["message"]
    assert google_message not in response.text
    assert "Gemini HTTP 404" in caplog.text
    assert "models/gemini-2.5-flash is no longer available to new users" in caplog.text
    assert "[REDACTED]" in caplog.text
    assert secret not in caplog.text
    assert secret not in response.text


def test_unrelated_http_404_is_not_reported_as_model_unavailable(c, monkeypatch, caplog):
    def fake_post(url, payload, key):
        body = json.dumps({"error": {"message": "The requested API endpoint was not found.", "status": "NOT_FOUND"}}).encode()
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(body))

    monkeypatch.setattr(chat, "api_key", lambda: "test-key")
    monkeypatch.setattr(chat, "post_json", fake_post)
    response = c.post("/api/chat", json={"message": "hi"})

    assert response.status_code == 502
    assert response.json()["error_code"] == "CHAT_PROVIDER_NOT_FOUND"
    assert "endpoint and configuration" in response.json()["message"]
    assert "requested API endpoint was not found" in caplog.text


def test_model_not_found_handles_malformed_google_error_body(c, monkeypatch, caplog):
    def fake_post(url, payload, key):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"not-json"))

    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "post_json", fake_post)
    response = c.post("/api/chat", json={"message": "hi"})

    assert response.status_code == 502
    assert response.json()["error_code"] == "CHAT_PROVIDER_NOT_FOUND"
    assert "no parseable error.message" in caplog.text


def test_authentication_error_never_exposes_api_key(c, monkeypatch, caplog):
    secret = "private-test-key"

    def fake_post(url, payload, key):
        body = json.dumps({"error": {"message": "API key not valid. Please pass a valid API key."}}).encode()
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(body))

    monkeypatch.setattr(chat, "api_key", lambda: secret)
    monkeypatch.setattr(chat, "post_json", fake_post)
    response = c.post("/api/chat", json={"message": "hi"})

    assert response.status_code == 502
    assert response.json()["error_code"] == "CHAT_AUTH_FAILED"
    assert secret not in response.text
    assert secret not in caplog.text


def test_network_error(c, monkeypatch):
    def fake_post(url, payload, key):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "post_json", fake_post)
    assert c.post("/api/chat", json={"message": "hi"}).json()["error_code"] == "CHAT_UNAVAILABLE"


def test_validation(c):
    assert c.post("/api/chat", json={"message": ""}).status_code == 422
