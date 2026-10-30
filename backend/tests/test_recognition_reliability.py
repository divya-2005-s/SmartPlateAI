"""Reliability checks for the accept / uncertain / unsupported / non-food decision. No TensorFlow: the real
FoodRecognizer.analyze_image code runs with a fake embedding step, so this tests the decision logic, not model quality."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.routes import analyze
from app.main import app
from app.ml.recognizer import FoodRecognizer
from app.ml.rejection import Thresholds, decide_batch, nearest_class

TH = Thresholds(food_mass_low=0.03, maha_high=100.0, conf_min=0.57, margin_min=0.24)
MEANS = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
PREC = np.eye(2)


def probs(top_idx, top=0.9):
    p = np.full(3, (1 - top) / 2)
    p[top_idx] = top
    return p


def test_nearest_class_matches_geometry():
    d, k = nearest_class(np.array([[9.0, 1.0], [0.5, 9.0]]), MEANS, PREC)
    assert list(k) == [1, 2] and d[0] == pytest.approx(2.0)


def test_confident_softmax_that_disagrees_with_features_is_uncertain():
    # softmax says class 0 with 90%, but the embedding sits on class 1's cluster: an unsupported or confused food
    out = decide_batch(np.array([probs(0)]), np.array([2.0]), np.array([0.8]), TH, nearest=np.array([1]))
    assert out[0] == "uncertain"
    # the same input without the check would have been accepted (the behaviour before this fix)
    assert decide_batch(np.array([probs(0)]), np.array([2.0]), np.array([0.8]), TH)[0] == "accept"


def test_agreeing_prediction_still_accepted():
    assert decide_batch(np.array([probs(1)]), np.array([2.0]), np.array([0.8]), TH, nearest=np.array([1]))[0] == "accept"


def test_far_images_keep_their_own_categories():
    far = np.array([500.0])
    assert decide_batch(np.array([probs(0)]), far, np.array([0.8]), TH, nearest=np.array([1]))[0] == "unsupported_food"
    assert decide_batch(np.array([probs(0)]), far, np.array([0.001]), TH, nearest=np.array([1]))[0] == "non_food"


def make_recognizer(feat, p, food_mass=0.8, agreement=True):
    rec = FoodRecognizer(model_dir="unused")
    rec.require_agreement = agreement
    rec.class_names = ["Apple", "Banana", "Cherry"]
    rec.thresholds, rec._means, rec._precision = TH, MEANS, PREC
    rec.prepare = lambda img: np.zeros((224, 224, 3), np.float32)
    rec.embed = lambda x: (np.array([p]), np.array([feat]), np.array([food_mass]))
    return rec


def test_analyze_image_reports_reason_and_signals():
    r = make_recognizer([9.5, 0.2], probs(0)).analyze_image(None)
    assert r["decision"] == "uncertain" and r["reason"] == "classifier_disagreement"
    assert r["signals"]["nearest_feature_class"] == "Banana"
    assert r["signals"]["decision_without_agreement_check"] == "accept"
    ok = make_recognizer([9.5, 0.2], probs(1)).analyze_image(None)
    assert ok["decision"] == "accept" and ok["reason"] is None and ok["top_k"][0]["food"] == "Banana"
    low = make_recognizer([9.5, 0.2], probs(1, top=0.45)).analyze_image(None)
    assert low["decision"] == "uncertain" and low["reason"] == "low_confidence"


def test_agreement_check_can_be_disabled():
    r = make_recognizer([9.5, 0.2], probs(0), agreement=False).analyze_image(None)
    assert r["decision"] == "accept"


# ---------------------------------------------------------------- API contract
class Rec:
    status_message = "ready"
    class_names = ["Apple", "Banana", "Cherry"]

    def __init__(self, decision, reason):
        self.decision, self.reason = decision, reason

    def load(self):
        return True

    def analyze_image(self, img):
        top = [{"class_id": 0, "food": "Apple", "score": 0.9}, {"class_id": 1, "food": "Banana", "score": 0.05}]
        return {"decision": self.decision, "reason": self.reason, "calibrated": True, "confidence": 0.9, "margin": 0.85,
                "top_k": top, "signals": {}}


class Nut:
    error = None

    def lookup(self, food, serving=None):
        return {"nutrients": []}


@pytest.fixture
def client():
    def use(rec):
        app.dependency_overrides[analyze.get_recognizer] = lambda: rec
        app.dependency_overrides[analyze.get_nutrition] = lambda: Nut()
        return TestClient(app)
    yield use
    app.dependency_overrides.clear()


def png():
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(b, "PNG")
    return b.getvalue()


def test_api_disagreement_is_low_confidence_with_candidates(client):
    r = client(Rec("uncertain", "classifier_disagreement")).post("/api/analyze/food", files={"file": ("a.png", png(), "image/png")})
    j = r.json()
    assert r.status_code == 422 and j["error_code"] == "LOW_CONFIDENCE" and j["reason"] == "classifier_disagreement"
    assert j["candidates"] and j["requires_confirmation"] and "different foods" in j["message"]


def test_api_unsupported_has_no_food_label(client):
    j = client(Rec("unsupported_food", "far_from_supported_foods")).post(
        "/api/analyze/food", files={"file": ("a.png", png(), "image/png")}).json()
    assert j["error_code"] == "UNSUPPORTED_FOOD" and "candidates" not in j and "prediction" not in j


def test_supported_foods_and_manual_food_confirmation(client):
    c = client(Rec("accept", None))
    assert c.get("/api/foods/supported").json()["foods"] == ["Apple", "Banana", "Cherry"]
    manual = c.post("/api/analyze/confirm", json={"food": "Pizza"}).json()
    assert manual["success"] and manual["confirmation"]["source"] == "user_selected"
    assert manual["identification"]["source"] == "user_selected" and manual["nutrition"] is None
    assert manual["nutrition_error"]
    j = c.post("/api/analyze/confirm", json={"food": "Banana"}).json()
    assert j["success"] and j["confirmation"]["source"] == "user_selected"


def test_diagnostic_script_runs_with_fake_model(tmp_path):
    import importlib.util
    from PIL import Image
    spec = importlib.util.spec_from_file_location("diag", "scripts/diagnose_recognition.py")
    diag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diag)
    for i in range(3):
        Image.new("RGB", (64, 64), (i * 50, 0, 0)).save(tmp_path / f"{i}.png")
    (tmp_path / "bad.jpg").write_bytes(b"nope")
    rec = make_recognizer([9.5, 0.2], probs(0))
    items = [(p, "Apple", "validation") for p in sorted(tmp_path.glob("*.png"))] + [(tmp_path / "bad.jpg", None, "your images")]
    rows = diag.analyse(rec, items)
    assert rows[0]["decision"] == "uncertain" and rows[0]["decision_before"] == "accept" and rows[-1]["decision"] == "error"
    text = "\n".join(diag.summarise(rows))
    assert "before (no agreement check)" in text and "| Apple | 3 | 3 | 0 | 0 |" in text
