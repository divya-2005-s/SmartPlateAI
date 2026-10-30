"""Non-food rejection: people, phones, laptops, shoes, vehicles, furniture, scenery and other objects must get NON_FOOD_IMAGE
with no food names, nutrition or freshness, without rejecting real food (alone, held by a person, or outside the 24 classes).

Part A checks the API's decision rules with a fake recognizer (no TensorFlow).
Part B runs the REAL production model on REAL openly licensed photos (data_nonfood/general, data_eval/*; provenance in each
folder's ATTRIBUTION.csv) through the real /api/analyze/food endpoint. The OpenAI/Gemini verdict is SIMULATED in every test
(no network or paid calls), so Part B measures the image model and the backend rules, not the vision provider.
Part B is skipped (reported as SKIPPED) when the model or the photos are missing."""
import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import ImageEnhance, ImageFilter

from app.api.routes import analyze
from app.main import app
from app.ml.recognizer import MSG_UNSUPPORTED
from app.ml.rejection import Thresholds

BACKEND = Path(__file__).resolve().parents[1]
MODEL_DIR = BACKEND / "models" / "production" / "food_classifier"
NON_FOOD_DIR, IN_CONTEXT_DIR, UNSUPPORTED_DIR = (BACKEND / "data_nonfood" / "general", BACKEND / "data_eval" / "food_in_context",
                                                 BACKEND / "data_eval" / "unsupported_food")
FORBIDDEN_KEYS = {"prediction", "nutrition", "freshness", "candidates", "identification", "general_candidate", "safety_alert",
                  "precautions", "pending_id", "image_ref"}
NO_FOOD = {"status": "no_food", "food_name": None, "supported_food": None, "visible_evidence": ["a smartphone on a desk"],
           "uncertainty": None, "category": None}
UNSURE = {**NO_FOOD, "status": "uncertain", "visible_evidence": [], "uncertainty": "too dark to tell"}
UNAVAILABLE = {"status": "unavailable", "reason": "quota_exhausted", "provider": "OpenAI Vision"}


def recognized(food):
    return {"status": "recognized", "food_name": food, "supported_food": food, "visible_evidence": [f"{food} in hand"],
            "uncertainty": None, "category": None, "provider": "Google Gemini"}


def unsupported(food):
    return {"status": "unsupported_food", "food_name": food, "supported_food": None, "visible_evidence": [food],
            "uncertainty": None, "category": None, "provider": "Google Gemini"}


@pytest.fixture
def provider(monkeypatch):
    """The OpenAI/Gemini identification each test simulates; Google Vision is off."""
    verdict = {"value": UNAVAILABLE}
    monkeypatch.setattr(analyze, "run_openai_vision", lambda img, names: dict(verdict["value"]))
    monkeypatch.setattr(analyze, "run_vision", lambda *a: None)
    return verdict


def assert_clean_non_food(body, class_names):
    """A non-food answer carries no food name, nutrition, calories or freshness anywhere in the response."""
    assert body["success"] is False and body["error_code"] == "NON_FOOD_IMAGE"
    assert body["message"] == "This image does not appear to contain a recognizable food item. Please upload a food image."
    assert not FORBIDDEN_KEYS & body.keys(), FORBIDDEN_KEYS & body.keys()
    text = json.dumps(body).lower()
    for word in ["calorie", "kcal", "nutrient", "ingredient", "fresh", "spoil"] + [c.lower() for c in class_names]:
        assert word not in text, f"non-food response mentions {word!r}"


# ====================================================================== Part A: decision rules (fake recognizer)
class GateRecognizer:
    """Mimics FoodRecognizer.analyze_image with chosen signals, using the production calibration's food-mass floor."""
    class_names = ["Apple", "Banana", "Donut"]
    thresholds = Thresholds(food_mass_low=0.0298, maha_high=2477.0, conf_min=0.574, margin_min=0.244)
    ready, status_message = True, "Food model ready."

    def __init__(self, decision, food_mass, confidence=0.71, reason=None, calibrated=True):
        self.decision, self.food_mass, self.confidence = decision, food_mass, confidence
        self.reason = reason if reason is not None else {"uncertain": "low_confidence", "accept": None}.get(decision, "far_from_supported_foods")
        if not calibrated:
            self.thresholds = None

    def load(self):
        return True

    def analyze_image(self, img):
        top = [{"class_id": 2, "food": "Donut", "score": self.confidence}, {"class_id": 0, "food": "Apple", "score": 0.1},
               {"class_id": 1, "food": "Banana", "score": 0.05}]
        return {"decision": self.decision, "reason": self.reason, "calibrated": self.thresholds is not None,
                "confidence": self.confidence, "margin": self.confidence - 0.1, "top_k": top, "features": None,
                "freshness": {"status": "fresh", "confidence": 0.9},  # would leak into a response that should have none
                "signals": {"imagenet_food_mass": self.food_mass, "feature_distance": 2100.0}}

    def assess_freshness(self, features, food):
        return {"status": "fresh", "confidence": 0.9}


def analyse(rec, img_bytes=None):
    from tests.test_recognition_packaged_history_fixes import png
    app.dependency_overrides[analyze.get_recognizer] = lambda: rec
    try:
        return TestClient(app).post("/api/analyze/food", files={"file": ("x.png", img_bytes or png(), "image/png")}).json()
    finally:
        app.dependency_overrides.pop(analyze.get_recognizer, None)


@pytest.mark.parametrize("decision", ["accept", "uncertain"])
def test_provider_no_food_plus_low_food_signal_is_non_food(provider, decision):
    """A phone the model calls 'Donut' (accepted at 71%, or uncertain): both independent checks say no food."""
    provider["value"] = NO_FOOD
    body = analyse(GateRecognizer(decision, food_mass=0.0126))
    assert_clean_non_food(body, GateRecognizer.class_names)
    assert body["reason"] == "no_food_confirmed" and body["recognition"]["status"] == "non_food"


def test_model_non_food_alone_is_non_food_without_any_food_data(provider):
    body = analyse(GateRecognizer("non_food", food_mass=0.004, confidence=0.3))
    assert_clean_non_food(body, GateRecognizer.class_names)
    assert body["reason"] == "far_from_supported_foods"


@pytest.mark.parametrize("food_mass", [0.0298, 0.1, 0.9])  # at or above the floor: the image model sees food evidence
def test_provider_no_food_alone_does_not_reject_food_evidence(provider, food_mass):
    """Only one check says 'no food' (e.g. the provider misses a small burger in a selfie): ambiguous -> uncertain."""
    provider["value"] = NO_FOOD
    body = analyse(GateRecognizer("accept", food_mass=food_mass, confidence=0.9))
    assert body["error_code"] == "LOW_CONFIDENCE" and body["reason"] == "openai_no_food" and body["requires_confirmation"]


@pytest.mark.parametrize("verdict", [UNAVAILABLE, UNSURE], ids=["provider_unavailable", "provider_unsure"])
def test_low_food_signal_alone_is_uncertain_not_non_food(provider, verdict):
    """Low model confidence and a low food signal are not proof of 'no food' without an explicit no-food verdict."""
    provider["value"] = verdict
    body = analyse(GateRecognizer("uncertain", food_mass=0.01, confidence=0.4))
    assert body["error_code"] == "LOW_CONFIDENCE" and body["requires_confirmation"] is True


def test_uncalibrated_rejection_never_promotes_to_non_food(provider):
    provider["value"] = NO_FOOD
    body = analyse(GateRecognizer("uncertain", food_mass=0.001, confidence=0.4, calibrated=False))
    assert body["error_code"] == "LOW_CONFIDENCE"


def test_provider_naming_a_food_overrides_a_model_non_food_verdict(provider):
    provider["value"] = recognized("Apple")
    assert analyse(GateRecognizer("non_food", food_mass=0.004))["error_code"] == "LOW_CONFIDENCE"


def test_unsupported_food_is_distinguished_from_non_food(provider):
    """Recognisable food outside the 24 classes is named as such (general identification), never 'non-food'."""
    provider["value"] = UNAVAILABLE
    body = analyse(GateRecognizer("unsupported_food", food_mass=0.6, confidence=0.5))
    assert body["error_code"] == "UNSUPPORTED_FOOD" and body["message"] == MSG_UNSUPPORTED
    provider["value"] = unsupported("Sushi")
    body = analyse(GateRecognizer("non_food", food_mass=0.02, confidence=0.3))
    assert body.get("error_code") != "NON_FOOD_IMAGE" and body["prediction"]["food"] == "Sushi"


@pytest.mark.real_quality
def test_poor_photo_is_never_called_non_food(provider):
    """A very dark photo: 'no food visible' is not reliable, so the user is asked for another photo, with no food guesses."""
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), (4, 4, 4)).save(buf, "PNG")
    body = analyse(GateRecognizer("non_food", food_mass=0.004, confidence=0.3), buf.getvalue())
    assert body["error_code"] == "LOW_CONFIDENCE" and body["reason"] == "poor_image_quality"
    assert body["candidates"] == [] and body["freshness"]["status"] == "not_assessed"


# ====================================================================== Part B: real model, real photos
def listed(folder: Path) -> list[tuple[Path, str]]:
    f = folder / "ATTRIBUTION.csv"
    return [(folder / r["file"], r["category"]) for r in csv.DictReader(open(f, encoding="utf-8"))] if f.is_file() else []


needs_model = pytest.mark.skipif(not (MODEL_DIR / "best.keras").is_file(), reason="production model not installed")


@pytest.fixture(scope="module")
def real():
    from app.ml.recognizer import FoodRecognizer
    rec = FoodRecognizer(MODEL_DIR)
    assert rec.load(), rec.status_message
    app.dependency_overrides[analyze.get_recognizer] = lambda: rec
    yield rec, TestClient(app)
    app.dependency_overrides.pop(analyze.get_recognizer, None)


def post_image(client, img_or_path):
    import io
    if isinstance(img_or_path, Path):
        data = img_or_path.read_bytes()
    else:
        buf = io.BytesIO()
        img_or_path.save(buf, "JPEG", quality=92)
        data = buf.getvalue()
    return client.post("/api/analyze/food", files={"file": ("photo.jpg", data, "image/jpeg")}).json()


def photos(folder, minimum):
    items = listed(folder)
    if len(items) < minimum:
        pytest.skip(f"NOT RUN: fewer than {minimum} reviewed photos listed in {folder.relative_to(BACKEND)}\\ATTRIBUTION.csv")
    return items


@needs_model
@pytest.mark.real_quality
def test_real_non_food_photos_are_rejected_without_food_data(real, provider):
    """64 reviewed photos: people, phones, laptops, keyboards, shoes, vehicles, furniture, scenery, objects, empty bowls.
    Simulated provider verdict: 'no food' (what a working provider is expected to say for these photos)."""
    rec, client = real
    provider["value"] = NO_FOOD
    items = photos(NON_FOOD_DIR, 20)
    outcomes = {}
    for path, category in items:
        body = post_image(client, path)
        assert body.get("success") is not True, f"{path.name} ({category}) was accepted as food: {body.get('prediction')}"
        outcomes[path.name] = (category, body["error_code"], body.get("reason"))
        if body["error_code"] == "NON_FOOD_IMAGE":
            assert_clean_non_food(body, rec.class_names)
        else:  # never a confident food claim; only an uncertain answer asking for another photo or a manual choice
            assert body["error_code"] == "LOW_CONFIDENCE" and "nutrition" not in body and "prediction" not in body
    rejected = sum(code == "NON_FOOD_IMAGE" for _, code, _ in outcomes.values())
    not_rejected = {k: v for k, v in outcomes.items() if v[1] != "NON_FOOD_IMAGE"}
    print(f"\nNON_FOOD_IMAGE: {rejected}/{len(outcomes)}; others: {not_rejected}")
    assert rejected / len(outcomes) >= 0.85, not_rejected  # measured 2026-10-16: 58/64; regression floor, not an estimate
    for must in ("person", "mobile_phone", "laptop", "keyboard", "shoe", "scenery"):
        cats = [code for cat, code, _ in outcomes.values() if cat == must]
        assert cats and sum(c == "NON_FOOD_IMAGE" for c in cats) / len(cats) >= 0.75, (must, cats)


@needs_model
def test_real_non_food_photos_image_model_alone(real):
    """Without any provider: how many non-food photos the image model's own gate rejects or holds back (reported)."""
    rec, _ = real
    from app.ml.recognizer import decode_upload
    items = photos(NON_FOOD_DIR, 20)
    decisions = {p.name: rec.analyze_image(decode_upload(p.read_bytes()))["decision"] for p, _ in items}
    accepted = [k for k, d in decisions.items() if d == "accept"]
    print(f"\nimage model alone: non_food {sum(d == 'non_food' for d in decisions.values())}/{len(decisions)}, accepted as food: {accepted}")
    assert len(accepted) / len(decisions) <= 0.05, accepted  # measured: 2/64 (a phone and a living room, both called 'Donut')


@needs_model
@pytest.mark.parametrize("verdict", ["provider_names_the_food", "provider_wrongly_says_no_food"])
def test_real_food_with_people_or_objects_is_not_rejected(real, provider, verdict):
    """12 reviewed photos of supported foods held, eaten or photographed among people and objects."""
    rec, client = real
    items = photos(IN_CONTEXT_DIR, 10)
    results = {}
    for path, food in items:
        provider["value"] = recognized(food) if verdict == "provider_names_the_food" else NO_FOOD
        body = post_image(client, path)
        results[path.name] = (food, body.get("error_code") or body["prediction"]["food"])
    rejected = [k for k, (_, out) in results.items() if out == "NON_FOOD_IMAGE"]
    named = sum(out == food for food, out in results.values())
    print(f"\n{verdict}: rejected as non-food {len(rejected)}/{len(results)}; correct food shown {named}; {results}")
    assert not rejected, rejected


@needs_model
@pytest.mark.parametrize("verdict", ["provider_names_it", "provider_unavailable"])
def test_real_unsupported_food_is_not_called_non_food(real, provider, verdict):
    """21 reviewed photos of foods outside the 24 classes (sushi, curry, cake, salad, pasta, dumplings, ...)."""
    rec, client = real
    items = photos(UNSUPPORTED_DIR, 10)
    outcomes = {}
    for path, food in items:
        provider["value"] = unsupported(food) if verdict == "provider_names_it" else UNAVAILABLE
        body = post_image(client, path)
        outcomes[path.name] = body.get("error_code") or ("general:" + body["prediction"]["food"]
                                                         if body["prediction"].get("class_id") is None else "class:" + body["prediction"]["food"])
    non_food = [k for k, v in outcomes.items() if v == "NON_FOOD_IMAGE"]
    print(f"\n{verdict}: {outcomes}")
    if verdict == "provider_names_it":
        assert not non_food, non_food
    else:  # image model alone; measured: 1/21 (zongzi in leaves, ImageNet food mass 0.018)
        assert len(non_food) / len(outcomes) <= 0.10, non_food


@needs_model
@pytest.mark.real_quality
def test_real_ambiguous_photos_are_uncertain_not_non_food(real, provider):
    """Real food-with-people photos made unreadable (heavy blur, near-black): the answer is 'uncertain, try another photo'."""
    rec, client = real
    from app.ml.recognizer import decode_upload
    provider["value"] = UNSURE
    items = photos(IN_CONTEXT_DIR, 10)
    codes = []
    for path, _ in items:
        img = decode_upload(path.read_bytes())
        for degraded in (img.filter(ImageFilter.GaussianBlur(25)), ImageEnhance.Brightness(img).enhance(0.08)):
            body = post_image(client, degraded)
            codes.append(body.get("error_code"))
            assert body.get("error_code") != "NON_FOOD_IMAGE" and body.get("success") is not True
            assert "nutrition" not in body
    print(f"\nambiguous: {len(codes)} photos, all {set(codes)}")


@needs_model
def test_real_supported_food_still_recognised(real, provider):
    """Held-out supported-food test photos (5 per class) with a provider that agrees: none is rejected as non-food."""
    import pandas as pd
    rec, client = real
    man = pd.read_csv(BACKEND / "data_prep" / "split_manifest.csv", low_memory=False)
    t = man[(man.new_split == "test") & (~man.is_augmented_copy.astype(bool))]
    sample = [(Path(p), f) for f, g in t.groupby("food") for p in g.sample(min(len(g), 5), random_state=3).image_path]
    rejected, correct = [], 0
    for path, food in sample:
        provider["value"] = recognized(food)
        body = post_image(client, path)
        if body.get("error_code") == "NON_FOOD_IMAGE":
            rejected.append(path.name)
        correct += bool(body.get("success") and body["prediction"]["food"] == food)
    print(f"\nsupported test photos: {len(sample)}, shown with the correct food {correct}, rejected as non-food {rejected}")
    assert not rejected and correct / len(sample) >= 0.9
