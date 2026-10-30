"""Gemini fallback for general food identification when OpenAI cannot answer (e.g. no credit).

All provider calls are MOCKED; the Gemini response bodies imitate the generateContent JSON shape. These tests check
routing, validation and labelling - not recognition accuracy (see scripts/evaluate_real_photos.py for real photos)."""
import json
import urllib.error
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.routes import analyze
from app.main import app
from app.services import gemini_vision, openai_vision, vision
from tests.test_freshness_nutrition_quality import RealishNutrition, ref  # noqa: F401  (fixture)
from tests.test_freshness_safety_automatic import FRESH_FEATS, ROTTEN_FEATS, HeadRecognizer
from tests.test_general_recognition import fake_usda
from tests.test_recognition_packaged_history_fixes import png

QUOTA = openai_vision.OpenAIVisionError("quota_exhausted")


def gemini_body(**fields) -> dict:
    payload = {"food_name": None, "supported_food": None, "visible_evidence": ["white liquid in a glass"], "contains_food": True,
               "uncertainty": None, "category": None, **fields}
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}


@pytest.fixture
def gem(monkeypatch):
    """Gemini service enabled with a fake key; `post` is replaced per test. Returns the list of calls made."""
    monkeypatch.setattr(gemini_vision, "get_settings", lambda: SimpleNamespace(
        gemini_vision_enabled=True, gemini_vision_model="model-a,model-b", gemini_vision_timeout_s=5))
    monkeypatch.setattr(gemini_vision.chat, "api_key", lambda: "test-key")
    calls = []
    state = {"replies": [gemini_body(food_name="Milk", category="Dairy")]}

    def post(url, payload, key, timeout):
        calls.append({"url": url, "key": key, "payload": payload})
        reply = state["replies"].pop(0) if len(state["replies"]) > 1 else state["replies"][0]
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(gemini_vision, "post", post)
    return SimpleNamespace(calls=calls, state=state)


def http_error(code):
    return urllib.error.HTTPError("https://example.invalid", code, "error", {}, None)


# ================================================================== the service itself
def test_gemini_returns_the_same_validated_shape_as_openai(gem):
    r = gemini_vision.identify(Image.new("RGB", (64, 64), "white"), ["Apple", "Banana"])
    assert r["status"] == "unsupported_food" and r["food_name"] == "Milk" and r["category"] == "Dairy"
    assert r["provider"] == "Google Gemini" and r["supported_food"] is None
    call = gem.calls[0]
    assert "test-key" not in call["url"] and call["key"] == "test-key"  # key only in the header, never in the URL
    parts = call["payload"]["contents"][0]["parts"]
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg" and "No confidence/probability" in parts[0]["text"]


def test_a_supported_class_named_by_gemini_maps_to_the_model_class(gem):
    gem.state["replies"] = [gemini_body(food_name="red apple", supported_food="Apple", category="Fruits")]
    r = gemini_vision.identify(Image.new("RGB", (64, 64), "red"), ["Apple", "Banana"])
    assert r["status"] == "recognized" and r["supported_food"] == "Apple"


def test_busy_model_moves_to_the_next_model_but_other_errors_do_not(gem):
    gem.state["replies"] = [http_error(503), gemini_body(food_name="Paneer", category="Dairy")]
    r = gemini_vision.identify(Image.new("RGB", (64, 64), "white"), ["Apple"])
    assert r["food_name"] == "Paneer" and [c["url"].split("/models/")[1].split(":")[0] for c in gem.calls] == ["model-a", "model-b"]
    gem.calls.clear()
    gem.state["replies"] = [http_error(429)]
    with pytest.raises(openai_vision.OpenAIVisionError) as e:
        gemini_vision.identify(Image.new("RGB", (64, 64), "white"), ["Apple"])
    assert e.value.code == "rate_limited" and len(gem.calls) == 1  # no retry storm


@pytest.mark.parametrize("reply,code", [({"candidates": []}, "invalid_response"),
                                        ({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}, "invalid_response")])
def test_malformed_gemini_replies_are_rejected(gem, reply, code):
    gem.state["replies"] = [reply]
    with pytest.raises(openai_vision.OpenAIVisionError) as e:
        gemini_vision.identify(Image.new("RGB", (64, 64), "white"), ["Apple"])
    assert e.value.code == code


def test_disabled_or_unconfigured_gemini_is_never_called(monkeypatch):
    monkeypatch.setattr(gemini_vision, "post", lambda *a: pytest.fail("Gemini must not be called"))
    monkeypatch.setattr(gemini_vision, "get_settings", lambda: SimpleNamespace(gemini_vision_enabled=False))
    assert gemini_vision.availability() == "disabled"
    monkeypatch.setattr(gemini_vision, "get_settings", lambda: SimpleNamespace(gemini_vision_enabled=True))
    monkeypatch.setattr(gemini_vision.chat, "api_key", lambda: "")
    assert gemini_vision.availability() == "not_configured"


# ================================================================== routing through the API
@pytest.fixture
def env(monkeypatch, ref, gem):  # noqa: F811
    state = {"rec": HeadRecognizer(FRESH_FEATS, food="Tomato", score=0.3, decision="unsupported_food", reason="far_from_supported_foods"),
             "oa": QUOTA, "oa_calls": 0}
    app.dependency_overrides[analyze.get_recognizer] = lambda: state["rec"]
    app.dependency_overrides[analyze.get_nutrition] = lambda: RealishNutrition(ref)
    monkeypatch.setattr(vision, "enabled", lambda: False)
    monkeypatch.setattr(openai_vision, "availability", lambda: "ready")

    def identify(img, classes):
        state["oa_calls"] += 1
        if isinstance(state["oa"], Exception):
            raise state["oa"]
        return state["oa"]
    monkeypatch.setattr(openai_vision, "identify", identify)
    monkeypatch.setattr(analyze, "run_condition", lambda img, q, is_food: {
        "status": "not_assessed", "confidence": None, "model_status": "not_installed", "message": "x"})
    fake_usda(monkeypatch)
    yield SimpleNamespace(state=state, gem=gem)
    app.dependency_overrides.clear()


def analyse(c=None):
    return (c or TestClient(app)).post("/api/analyze/food", files={"file": ("f.png", png("white"), "image/png")}).json()


def test_openai_without_credit_falls_back_to_gemini_for_milk(env):
    j = analyse()
    assert j["success"] and j["prediction"]["food"] == "Milk" and j["identification"]["verified_by"] == ["Google Gemini"]
    assert j["identification"]["provider"] == "Google Gemini" and "Identified by Google Gemini" in j["recognition"]["message"]
    assert j["openai_vision"]["fallback_from"] == {"provider": "OpenAI Vision", "reason": "quota_exhausted"}
    assert j["nutrition"]["matched_description"] == "Milk, NFS" and j["prediction"]["confidence"] is None
    assert "not supported for Milk" in j["freshness"]["message"]
    assert env.state["oa_calls"] == 1 and len(env.gem.calls) == 1  # one call per provider, no retries


def test_gemini_agreement_verifies_a_supported_food_and_freshness_still_runs(env):
    env.state["rec"] = HeadRecognizer(ROTTEN_FEATS, food="Apple", score=0.55)
    env.gem.state["replies"] = [gemini_body(food_name="Apple", supported_food="Apple", category="Fruits")]
    j = analyse()
    assert j["success"] and j["identification"]["verified_by"][:2] == ["SmartPlateAI image model", "Google Gemini"]
    assert j["requires_confirmation"] is False and "Google Gemini identified the same supported food" in j["recognition"]["message"]
    assert j["freshness"]["status"] == "possibly_spoiled" and j["safety_alert"]["level"] == "danger"


def test_gemini_disagreement_with_a_confident_class_asks_and_names_gemini(env):
    env.state["rec"] = HeadRecognizer(FRESH_FEATS, food="Tomato", score=0.9)
    env.gem.state["replies"] = [gemini_body(food_name="Red cabbage", category="Vegetables")]
    j = analyse()
    assert j["error_code"] == "LOW_CONFIDENCE" and j["general_candidate"]["source"] == "Google Gemini"
    assert "Google Gemini identified food outside" in j["message"]


def test_openai_success_never_calls_gemini(env):
    env.state["oa"] = {"status": "unsupported_food", "food_name": "Paneer", "supported_food": None, "visible_evidence": [],
                       "uncertainty": None, "category": "Dairy"}
    j = analyse()
    assert j["identification"]["provider"] == "OpenAI Vision" and env.gem.calls == []


def test_both_providers_failing_is_reported_and_no_food_is_invented(env):
    env.gem.state["replies"] = [http_error(429)]
    j = analyse()  # the image model says "not one of my foods"
    assert j["error_code"] == "UNSUPPORTED_FOOD" and "prediction" not in j
    assert j["openai_vision"]["reason"] == "quota_exhausted" and j["openai_vision"]["fallback"]["reason"] == "rate_limited"
    env.state["rec"] = HeadRecognizer(FRESH_FEATS, food="Apple", score=0.95)
    k = analyse()
    assert k["success"] and "Google Gemini fallback also failed (rate limited)" in k["recognition"]["message"]


def test_confirming_a_gemini_suggestion_keeps_the_provider(env):
    env.state["rec"] = HeadRecognizer(FRESH_FEATS, food="Tomato", score=0.9)
    env.gem.state["replies"] = [gemini_body(food_name="Paneer", category="Dairy")]
    c = TestClient(app)
    low = analyse(c)
    j = c.post("/api/analyze/confirm", json={"food": "Paneer", "pending_id": low["pending_id"]}).json()
    assert j["identification"]["verified_by"] == ["Google Gemini", "You"] and "suggested by Google Gemini" in j["recognition"]["message"]
