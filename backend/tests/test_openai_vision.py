"""OpenAI vision fusion tests; SDK responses are mocked and no paid calls are made."""
import base64
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APITimeoutError, AuthenticationError, PermissionDeniedError, RateLimitError
from PIL import Image

from app.api.routes import analyze
from app.main import app
from app.services import openai_vision, vision

CLASSES = ["Apple", "Banana", "Taco", "Tomato"]


class FakeRecognizer:
    status_message = "ready"
    class_names = CLASSES

    def __init__(self, decision="accept", food="Apple", reason=None):
        self.decision, self.food, self.reason = decision, food, reason

    def load(self):
        return True

    def analyze_image(self, img):
        top = [{"class_id": CLASSES.index(self.food), "food": self.food, "score": 0.9},
               {"class_id": 1, "food": "Banana", "score": 0.05}]
        return {"decision": self.decision, "reason": self.reason, "calibrated": True, "confidence": 0.9, "margin": 0.85,
                "top_k": top, "signals": {}, "freshness": {"status": "not_assessed", "confidence": None, "message": "Not assessed."}}


class FakeNutrition:
    error = None

    def lookup(self, food, serving=None):
        return {"basis": "per 100 g", "nutrients": [], "not_available": []}


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(buffer, "PNG")
    return buffer.getvalue()


def identified(food="Apple", supported="Apple", contains=True):
    return {
        "status": "recognized" if supported else "unsupported_food" if contains else "no_food",
        "food_name": food,
        "supported_food": supported,
        "visible_evidence": ["round red fruit"],
        "uncertainty": None,
    }


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[analyze.get_recognizer] = lambda: FakeRecognizer()
    app.dependency_overrides[analyze.get_nutrition] = lambda: FakeNutrition()
    monkeypatch.setattr(vision, "enabled", lambda: False)
    settings = SimpleNamespace(openai_vision_enabled=True, openai_api_key="mocked",
                               openai_vision_model="gpt-4.1-mini", openai_vision_timeout_s=12)
    monkeypatch.setattr(openai_vision, "get_settings", lambda: settings)
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: identified())
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def post(client):
    return client.post("/api/analyze/food", files={"file": ("food.png", png(), "image/png")})


def test_same_supported_food_returns_compatible_verified_response(client):
    response = post(client)
    body = response.json()
    assert response.status_code == 200 and body["success"] is True
    assert body["prediction"]["food"] == "Apple" and body["nutrition"] is not None
    assert body["recognition"]["status"] == "verified_both"
    assert body["openai_vision"]["supported_food"] == "Apple"
    assert body["vision"] is None and body["freshness"] and body["warnings"] == []


def test_supported_food_disagreement_requires_confirmation_without_nutrition(client, monkeypatch):
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: identified("Banana", "Banana"))
    body = post(client).json()
    assert body["error_code"] == "LOW_CONFIDENCE"
    assert body["reason"] == "openai_disagreement" and body["requires_confirmation"]
    assert body["openai_vision"]["supported_food"] == "Banana"
    assert "nutrition" not in body


def test_openai_unsupported_food_is_not_forced_into_a_classifier_class(client, monkeypatch):
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: identified("Durian", None))
    body = post(client).json()
    assert body["error_code"] == "LOW_CONFIDENCE"
    assert body["reason"] == "openai_unsupported_food"
    assert body["openai_vision"]["food_name"] == "Durian"
    assert body["openai_vision"]["supported_food"] is None and "nutrition" not in body


def test_red_onion_name_cannot_be_overridden_to_tomato(client, monkeypatch):
    # Simulates a structured response whose free-form name contradicts its class field.
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: {
        "status": "unsupported_food", "food_name": "Red Onion", "supported_food": None,
        "visible_evidence": ["purple-red papery bulb"], "uncertainty": None,
    })
    body = post(client).json()
    assert body["error_code"] == "LOW_CONFIDENCE"
    assert body["reason"] == "openai_unsupported_food" and body["requires_confirmation"]
    assert body["openai_vision"]["food_name"] == "Red Onion"
    assert body["openai_vision"]["supported_food"] is None
    assert "nutrition" not in body


def test_contradictory_openai_name_and_supported_label_cannot_verify_tomato(client, monkeypatch):
    app.dependency_overrides[analyze.get_recognizer] = lambda: FakeRecognizer(food="Tomato")
    response = SimpleNamespace(output_text=json.dumps({
        "food_name": "Red Onion", "supported_food": "Tomato", "visible_evidence": ["purple-red papery bulb"],
        "contains_food": True, "uncertainty": None,
    }))
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: openai_vision._parse_output(response, classes))
    body = post(client).json()
    assert body["error_code"] == "LOW_CONFIDENCE"
    assert body["reason"] == "openai_unsupported_food"
    assert body["recognition"]["status"] == "confirmation_required"
    assert body["candidates"][0]["food"] == "Tomato"
    assert body["openai_vision"]["food_name"] == "Red Onion"
    assert body["openai_vision"]["supported_food"] is None
    assert "nutrition" not in body


def test_openai_no_food_requires_confirmation(client, monkeypatch):
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: identified(None, None, False))
    body = post(client).json()
    assert body["error_code"] == "LOW_CONFIDENCE"
    assert body["reason"] == "openai_no_food" and body["requires_confirmation"]
    assert body["openai_vision"]["status"] == "no_food" and "nutrition" not in body


def test_openai_unclear_food_requires_confirmation(client, monkeypatch):
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: {
        "status": "uncertain", "food_name": None, "supported_food": None,
        "visible_evidence": ["partly obscured food"], "uncertainty": "The item is too unclear to identify.",
    })
    body = post(client).json()
    assert body["error_code"] == "LOW_CONFIDENCE"
    assert body["reason"] == "openai_uncertain" and body["requires_confirmation"]
    assert body["openai_vision"]["status"] == "uncertain" and "nutrition" not in body


def test_openai_timeout_requires_confirmation_instead_of_silent_fallback(client, monkeypatch):
    monkeypatch.setattr(analyze, "get_settings", lambda: SimpleNamespace(openai_failure_policy="confirm"))  # stricter opt-in policy
    # Changed behaviour: a configured OpenAI that fails no longer lets the image model's answer through unchecked
    # (this is how "Tomato 82.9%" could be shown for a red onion). OPENAI_FAILURE_POLICY=fallback restores the old rule.
    def timeout(img, classes):
        raise openai_vision.OpenAIVisionError("timeout")

    monkeypatch.setattr(openai_vision, "identify", timeout)
    body = post(client).json()
    assert body["error_code"] == "LOW_CONFIDENCE" and body["reason"] == "openai_unavailable" and body["requires_confirmation"]
    assert "timeout" in body["message"] and body["candidates"][0]["food"] == "Apple" and "nutrition" not in body
    assert body["openai_vision"]["reason"] == "timeout"


def test_openai_timeout_falls_back_when_policy_is_fallback(client, monkeypatch):
    from app.api.routes import analyze as analyze_route
    monkeypatch.setattr(analyze_route, "get_settings", lambda: SimpleNamespace(openai_failure_policy="fallback"))
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: (_ for _ in ()).throw(openai_vision.OpenAIVisionError("timeout")))
    body = post(client).json()
    assert body["success"] is True and body["prediction"]["food"] == "Apple"
    assert body["recognition"]["status"] == "tensorflow_fallback"
    assert body["openai_vision"]["reason"] == "timeout"


def test_openai_rate_limit_does_not_silently_accept_tomato(client, monkeypatch):
    monkeypatch.setattr(analyze, "get_settings", lambda: SimpleNamespace(openai_failure_policy="confirm"))  # stricter opt-in policy
    app.dependency_overrides[analyze.get_recognizer] = lambda: FakeRecognizer(food="Tomato")
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: (_ for _ in ()).throw(
        openai_vision.OpenAIVisionError("rate_limited")))
    body = post(client).json()
    assert body["error_code"] == "LOW_CONFIDENCE"
    assert body["reason"] == "openai_unavailable" and body["requires_confirmation"]
    assert body["candidates"][0]["food"] == "Tomato"
    assert body["openai_vision"]["reason"] == "rate_limited"
    assert body["recognition"]["status"] == "confirmation_required"
    assert "nutrition" not in body


def test_missing_openai_key_does_not_call_provider(client, monkeypatch):
    settings = SimpleNamespace(openai_vision_enabled=True, openai_api_key="")
    monkeypatch.setattr(openai_vision, "get_settings", lambda: settings)
    monkeypatch.setattr(openai_vision, "identify", lambda *args: pytest.fail("OpenAI must not be called without a key"))
    body = post(client).json()
    assert body["success"] is True
    assert body["recognition"]["status"] == "tensorflow_fallback"
    assert body["openai_vision"]["reason"] == "not_configured"


def test_malformed_provider_response_requires_confirmation(client, monkeypatch):
    monkeypatch.setattr(analyze, "get_settings", lambda: SimpleNamespace(openai_failure_policy="confirm"))  # stricter opt-in policy
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: (_ for _ in ()).throw(
        openai_vision.OpenAIVisionError("invalid_response")))
    body = post(client).json()
    assert body["error_code"] == "LOW_CONFIDENCE" and body["reason"] == "openai_unavailable"
    assert body["openai_vision"]["reason"] == "invalid_response"
    assert body["recognition"]["status"] == "confirmation_required"


def test_google_vision_still_provides_second_opinion_when_openai_times_out(client, monkeypatch):
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: (_ for _ in ()).throw(
        openai_vision.OpenAIVisionError("timeout")))
    monkeypatch.setattr(vision, "enabled", lambda: True)
    monkeypatch.setattr(vision, "annotate", lambda img: {"labels": [{"name": "Apple", "score": 0.95}], "objects": []})
    body = post(client).json()
    assert body["success"] is True
    assert body["vision"]["status"] == "agrees"
    assert body["recognition"]["status"] == "tensorflow_fallback"


def test_sdk_request_uses_configured_model_and_in_memory_image(monkeypatch):
    settings = SimpleNamespace(openai_vision_enabled=True, openai_api_key="unit-test-key",
                               openai_vision_model="gpt-4.1-mini", openai_vision_timeout_s=12)
    monkeypatch.setattr(openai_vision, "get_settings", lambda: settings)
    calls = {}

    class Responses:
        def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(output_text=json.dumps({
                "food_name": "Apple", "supported_food": "Apple", "visible_evidence": ["red skin"],
                "contains_food": True, "uncertainty": None,
            }))

    class Client:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.responses = Responses()

    monkeypatch.setattr(openai_vision, "OpenAI", Client)
    result = openai_vision.identify(Image.new("RGB", (64, 64), "red"), CLASSES)
    image_url = calls["input"][0]["content"][1]["image_url"]
    assert calls["model"] == "gpt-4.1-mini" and calls["client"]["timeout"] == 12
    assert json.dumps(CLASSES) in calls["input"][0]["content"][0]["text"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(image_url.split(",", 1)[1]).startswith(b"\xff\xd8")
    assert result["supported_food"] == "Apple"
    assert "unit-test-key" not in json.dumps(calls["input"])


def test_invalid_json_from_openai_is_rejected(monkeypatch):
    settings = SimpleNamespace(openai_vision_enabled=True, openai_api_key="unit-test-key",
                               openai_vision_model="gpt-4.1-mini", openai_vision_timeout_s=12)
    monkeypatch.setattr(openai_vision, "get_settings", lambda: settings)

    class Responses:
        def create(self, **kwargs):
            return SimpleNamespace(output_text="not JSON")

    class Client:
        def __init__(self, **kwargs):
            self.responses = Responses()

    monkeypatch.setattr(openai_vision, "OpenAI", Client)
    with pytest.raises(openai_vision.OpenAIVisionError, match="invalid_response"):
        openai_vision.identify(Image.new("RGB", (64, 64), "red"), CLASSES)


def test_parser_keeps_unmatched_food_unsupported_and_unidentified_food_uncertain():
    unsupported = SimpleNamespace(output_text=json.dumps({
        "food_name": "Durian", "supported_food": "Durian", "visible_evidence": ["spiky green rind"],
        "contains_food": True, "uncertainty": None,
    }))
    unclear = SimpleNamespace(output_text=json.dumps({
        "food_name": None, "supported_food": None, "visible_evidence": ["partly obscured food"],
        "contains_food": True, "uncertainty": "The image is too unclear to identify.",
    }))
    assert openai_vision._parse_output(unsupported, CLASSES)["status"] == "unsupported_food"
    assert openai_vision._parse_output(unclear, CLASSES)["status"] == "uncertain"


def test_parser_rejects_unsupported_name_even_when_supported_field_says_tomato():
    response = SimpleNamespace(output_text=json.dumps({
        "food_name": "Red Onion", "supported_food": "Tomato", "visible_evidence": ["red-purple bulb"],
        "contains_food": True, "uncertainty": None,
    }))
    result = openai_vision._parse_output(response, ["Tomato", "Apple"])
    assert result["status"] == "unsupported_food"
    assert result["food_name"] == "Red Onion" and result["supported_food"] is None


def test_parser_marks_conflicting_supported_class_and_food_name_uncertain():
    response = SimpleNamespace(output_text=json.dumps({
        "food_name": "Apple", "supported_food": "Tomato", "visible_evidence": ["round red fruit"],
        "contains_food": True, "uncertainty": None,
    }))
    result = openai_vision._parse_output(response, ["Tomato", "Apple"])
    assert result["status"] == "uncertain" and result["supported_food"] is None


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        ("timeout", "timeout"),
        ("authentication", "authentication_failed"),
        ("permission", "authentication_failed"),
        ("rate_limit", "rate_limited"),
        ("network", "network_error"),
    ],
)
def test_sdk_provider_errors_are_mapped_without_exposing_diagnostics(monkeypatch, error_type, expected):
    settings = SimpleNamespace(openai_vision_enabled=True, openai_api_key="unit-test-key",
                               openai_vision_model="gpt-4.1-mini", openai_vision_timeout_s=12)
    monkeypatch.setattr(openai_vision, "get_settings", lambda: settings)
    exception_type = {
        "timeout": APITimeoutError,
        "authentication": AuthenticationError,
        "permission": PermissionDeniedError,
        "rate_limit": RateLimitError,
        "network": APIConnectionError,
    }[error_type]
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    status = 401 if error_type == "authentication" else 403 if error_type == "permission" else 429
    response = httpx.Response(status, request=request)
    if error_type in ("authentication", "permission", "rate_limit"):
        error = exception_type("private provider detail", response=response, body=None)
    elif error_type == "timeout":
        error = exception_type(request=request)
    else:
        error = exception_type(message="private provider detail", request=request)

    class Responses:
        def create(self, **kwargs):
            raise error

    class Client:
        def __init__(self, **kwargs):
            self.responses = Responses()

    monkeypatch.setattr(openai_vision, "OpenAI", Client)
    with pytest.raises(openai_vision.OpenAIVisionError) as raised:
        openai_vision.identify(Image.new("RGB", (64, 64), "red"), CLASSES)
    assert raised.value.code == expected
    assert "private" not in str(raised.value)
