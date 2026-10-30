"""API contract tests with a FAKE recognizer (no TensorFlow needed). They check HTTP behaviour and messages, not model quality."""
import io
import math

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.routes import analyze
from app.main import app

NON_FOOD_MSG = "This image does not appear to contain a recognizable food item. Please upload a food image."


class FakeRecognizer:
    def __init__(self, decision="accept", ready=True, confidence=0.93, reason=None):
        self.decision, self.ready, self.confidence = decision, ready, confidence
        self.reason = reason if reason is not None else ("low_confidence" if decision == "uncertain" else None)
        self.status_message = "Food model ready." if ready else "The food recognition model is not installed."
        self.class_names = ["Apple", "Banana"]

    def load(self):
        return self.ready

    def info(self):
        return {"status": "ready" if self.ready else "model_missing", "message": self.status_message}

    def analyze_image(self, img):
        score = self.confidence if isinstance(self.confidence, (int, float)) and math.isfinite(self.confidence) \
            and 0 <= self.confidence <= 1 else 0.05
        top = [{"class_id": 0, "food": "Apple", "score": score}, {"class_id": 1, "food": "Banana", "score": 0.04}]
        return {"decision": self.decision, "reason": self.reason, "calibrated": True, "confidence": self.confidence,
                "margin": 0.89, "top_k": top, "signals": {}}


class FakeNutrition:
    error = None

    def lookup(self, food, serving=None):
        return {"nutrients": [], "is_estimate": True} if food == "Apple" else None


def png_bytes(fmt="PNG", size=(64, 64)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


@pytest.fixture
def client():
    def use(rec, nutrition=None):
        app.dependency_overrides[analyze.get_recognizer] = lambda: rec
        app.dependency_overrides[analyze.get_nutrition] = lambda: nutrition or FakeNutrition()
        return TestClient(app)
    yield use
    app.dependency_overrides.clear()


def post(c, data, name="a.png", ctype="image/png", **form):
    return c.post("/api/analyze/food", files={"file": (name, data, ctype)}, data=form)


def test_health_still_works(client):
    r = client(FakeRecognizer()).get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_valid_food(client):
    r = post(client(FakeRecognizer()), png_bytes())
    j = r.json()
    assert r.status_code == 200 and j["success"] is True and j["prediction"]["food"] == "Apple"
    assert j["nutrition"]["is_estimate"] is True and 0 <= j["prediction"]["confidence"] <= 1


def test_non_food_message_and_status(client):
    r = post(client(FakeRecognizer("non_food")), png_bytes())
    body = r.json()
    assert r.status_code == 422
    assert {key: body[key] for key in ("success", "error_code", "message")} == {
        "success": False, "error_code": "NON_FOOD_IMAGE", "message": NON_FOOD_MSG,
    }
    assert body["recognition"]["status"] == "non_food"
    assert body["openai_vision"]["reason"] == "disabled"


@pytest.mark.parametrize("decision,code", [("uncertain", "LOW_CONFIDENCE"), ("unsupported_food", "UNSUPPORTED_FOOD")])
def test_low_confidence_and_unsupported_give_no_food_label(client, decision, code):
    r = post(client(FakeRecognizer(decision, confidence=0.69)), png_bytes())  # below the 70% auto-accept rule
    body = r.json()
    assert r.status_code == 422 and body["error_code"] == code and "prediction" not in body and "nutrition" not in body
    if decision == "uncertain":
        assert body["candidates"][0]["food"] == "Apple" and body["requires_confirmation"] is True
    else:
        assert "candidates" not in body


@pytest.mark.parametrize("score", [0.85, 0.71, 0.7])  # exactly 70% is accepted (requirement changed 2026-10-15)
def test_low_score_rejection_at_or_above_70_percent_is_accepted(client, score):
    response = post(client(FakeRecognizer("uncertain", confidence=score)), png_bytes())
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["prediction"]["food"] == "Apple"
    assert body["prediction"]["confidence"] == score


@pytest.mark.parametrize("score", [0.69, 0.6999, 0.4])
def test_score_below_70_percent_still_requires_confirmation(client, score):
    response = post(client(FakeRecognizer("uncertain", confidence=score)), png_bytes())
    body = response.json()
    assert response.status_code == 422
    assert body["error_code"] == "LOW_CONFIDENCE"
    assert body["confidence"] == score
    assert body["requires_confirmation"] is True


@pytest.mark.parametrize("score", [None, float("nan"), float("inf"), 1.01])
def test_missing_or_invalid_score_never_auto_accepts(client, score):
    response = post(client(FakeRecognizer("uncertain", confidence=score)), png_bytes())
    body = response.json()
    assert response.status_code == 422
    assert body["error_code"] == "LOW_CONFIDENCE"
    assert body["requires_confirmation"] is True
    assert "confidence" not in body


def test_high_score_does_not_override_model_disagreement(client):
    response = post(client(FakeRecognizer("uncertain", confidence=0.85, reason="classifier_disagreement")), png_bytes())
    body = response.json()
    assert response.status_code == 422
    assert body["error_code"] == "LOW_CONFIDENCE"
    assert body["reason"] == "classifier_disagreement"


def test_unreadable_image(client):
    r = post(client(FakeRecognizer()), b"this is not an image")
    assert r.status_code == 400 and r.json()["error_code"] == "INVALID_IMAGE"


def test_unsupported_format(client):
    r = post(client(FakeRecognizer()), png_bytes("GIF"), "a.gif", "image/gif")
    assert r.status_code == 415 and r.json()["error_code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_oversized_upload(client, monkeypatch):
    monkeypatch.setattr(analyze, "MAX_BYTES", 500)
    r = post(client(FakeRecognizer()), png_bytes(size=(300, 300)))
    assert r.status_code == 413 and r.json()["error_code"] == "FILE_TOO_LARGE"


def test_empty_upload(client):
    assert post(client(FakeRecognizer()), b"").json()["error_code"] == "INVALID_IMAGE"


def test_model_missing_is_explicit(client):
    r = post(client(FakeRecognizer(ready=False)), png_bytes())
    assert r.status_code == 503 and r.json()["error_code"] == "MODEL_UNAVAILABLE" and "not installed" in r.json()["message"]


def test_invalid_serving_size(client):
    r = post(client(FakeRecognizer()), png_bytes(), serving_grams="-5")
    assert r.status_code == 422 and r.json()["error_code"] == "INVALID_SERVING"


def test_models_status_does_not_leak_paths(client):
    r = client(FakeRecognizer()).get("/api/models/status")
    assert r.status_code == 200 and "\\" not in r.text and "D:" not in r.text


def test_confirm_supported_food(client):
    r = client(FakeRecognizer()).post("/api/analyze/confirm", json={"food": "Apple", "serving_grams": 150})
    j = r.json()
    assert r.status_code == 200
    assert j["success"] is True
    assert j["confirmation"] == {"food": "Apple", "source": "user_selected"}
    assert j["nutrition"]["is_estimate"] is True
    assert j["nutrition_error"] is None
    assert any("not independently verified" in note for note in j["notes"])
    assert any("reference data" in note for note in j["notes"])


def test_confirm_manual_food_uses_verified_usda_nutrition(client, monkeypatch):
    reference = {"basis": "USDA FoodData Central", "is_estimate": True, "nutrients": []}
    monkeypatch.setattr(analyze.usda, "lookup", lambda food, category, serving: {
        "status": "found", "nutrition": reference,
    })
    response = client(FakeRecognizer()).post("/api/analyze/confirm", json={"food": "Red Onion", "serving_grams": 120})
    body = response.json()
    assert response.status_code == 200 and body["success"] is True
    assert body["confirmation"] == {"food": "Red Onion", "source": "user_selected"}
    assert body["identification"]["source"] == "user_selected"
    assert body["identification"]["verified_by"] == ["You"]
    assert body["nutrition"] == reference
    assert "not identified or verified by the image model" in body["notes"][0]


def test_confirm_manual_food_with_no_reference_reports_unavailable_nutrition(client, monkeypatch):
    monkeypatch.setattr(analyze.usda, "lookup", lambda food, category, serving: {
        "status": "no_match", "message": "No verified USDA reference record clearly matches this food.",
    })
    response = client(FakeRecognizer()).post("/api/analyze/confirm", json={"food": "Imaginary fruit"})
    body = response.json()
    assert response.status_code == 200 and body["success"] is True
    assert body["identification"]["source"] == "user_selected"
    assert body["nutrition"] is None
    assert "No verified USDA reference record" in body["nutrition_error"]


def test_confirm_manual_food_rejects_empty_name(client):
    response = client(FakeRecognizer()).post("/api/analyze/confirm", json={"food": "   "})
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_FOOD_SELECTION"


def test_confirm_supported_food_is_case_insensitive(client):
    response = client(FakeRecognizer()).post("/api/analyze/confirm", json={"food": "apple"})
    body = response.json()
    assert response.status_code == 200
    assert body["confirmation"]["food"] == "Apple"
    assert body["identification"]["source"] == "user_selected"


def test_confirm_manual_food_without_nutrition_reports_unavailable(client, monkeypatch):
    monkeypatch.setattr(analyze.usda, "lookup", lambda food, category, serving: {
        "status": "unavailable", "message": "USDA FoodData Central is not configured.",
    })
    r = client(FakeRecognizer()).post("/api/analyze/confirm", json={"food": "Durian"})
    body = r.json()
    assert r.status_code == 200 and body["success"] is True
    assert body["identification"]["source"] == "user_selected"
    assert body["nutrition"] is None
    assert body["nutrition_error"] == "USDA FoodData Central is not configured."


def test_confirm_requires_available_model(client):
    r = client(FakeRecognizer(ready=False)).post("/api/analyze/confirm", json={"food": "Apple"})
    assert r.status_code == 503
    assert r.json()["error_code"] == "MODEL_UNAVAILABLE"


@pytest.mark.parametrize("serving_grams", [0, 2001])
def test_confirm_rejects_invalid_serving_size(client, serving_grams):
    r = client(FakeRecognizer()).post("/api/analyze/confirm", json={"food": "Apple", "serving_grams": serving_grams})
    assert r.status_code == 422


def test_confirm_reports_unavailable_nutrition(client):
    class MissingNutrition:
        error = "Nutrition reference data was not found."

        def lookup(self, food, serving=None):
            return None

    r = client(FakeRecognizer(), MissingNutrition()).post("/api/analyze/confirm", json={"food": "Apple"})
    j = r.json()
    assert r.status_code == 200
    assert j["success"] is True
    assert j["nutrition"] is None
    assert j["nutrition_error"] == "Nutrition reference data was not found."