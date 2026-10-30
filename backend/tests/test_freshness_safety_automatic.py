"""Freshness wiring, rotten-food safety precautions, automatic results, food-specific nutrition and unknown packaged products.

Recognizer outputs, embeddings, the nutrition CSV and packaged products are SYNTHETIC fixtures; every external provider
(OpenAI, Google Vision, USDA, Open Food Facts, Tesseract) is mocked. These tests check behaviour and API contracts, not
real-world accuracy."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.routes import analyze
from app.api.routes import packaged as packaged_route
from app.main import app
from app.ml import freshness as F
from app.ml.recognizer import FoodRecognizer
from app.services import openai_vision, precautions, usda, vision
from app.services import openfoodfacts as off
from tests.test_freshness_nutrition_quality import RealishNutrition, ref  # noqa: F401  (fixture)
from tests.test_packaged_recognition import BACK, dataset
from tests.test_recognition_packaged_history_fixes import CLASSES, FakeRecognizer, png
from tests.test_recognition_packaged_history_fixes import oa as openai_result


# ------------------------------------------------------------------ a real FreshnessHead on synthetic embeddings
def trained_head(supported=("Apple", "Banana")) -> F.FreshnessHead:
    """Feature 0 high = spoiled. Thresholds as the training script would store them."""
    rng = np.random.default_rng(0)
    y = np.repeat([0, 1], 200)
    x = rng.normal(0, 1, (400, 4))
    x[:, 0] += np.where(y == 1, 3.0, -3.0)
    h = F.FreshnessHead(model_dir=None)
    h.head = F.fit_logistic(x, y)
    h.cfg, h.status = {"supported_foods": list(supported), "t_fresh": 0.2, "t_spoiled": 0.8}, "ready"
    return h


FRESH_FEATS, ROTTEN_FEATS, MIDDLE_FEATS = np.array([-3.0, 0, 0, 0]), np.array([3.0, 0, 0, 0]), np.array([0.0, 0, 0, 0])


class HeadRecognizer(FakeRecognizer):
    """FakeRecognizer + embeddings + the real FoodRecognizer.assess_freshness/FreshnessHead code path."""

    def __init__(self, feats, **kw):
        super().__init__(**kw)
        self.feats, self.freshness = feats, trained_head()

    def analyze_image(self, img):
        r = super().analyze_image(img)
        accepted = r["decision"] == "accept"
        r["freshness"] = self.freshness.assess(self.feats, self.food if accepted else None, accepted)
        r["features"] = self.feats
        return r

    assess_freshness = FoodRecognizer.assess_freshness


@pytest.fixture
def env(monkeypatch, ref):  # noqa: F811
    state = {"rec": HeadRecognizer(ROTTEN_FEATS, food="Banana", score=0.95), "oa": {"status": "unavailable", "reason": "not_configured"}}
    app.dependency_overrides[analyze.get_recognizer] = lambda: state["rec"]
    app.dependency_overrides[analyze.get_nutrition] = lambda: RealishNutrition(ref)
    monkeypatch.setattr(vision, "enabled", lambda: False)
    monkeypatch.setattr(openai_vision, "availability", lambda: "ready")
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: state["oa"])
    monkeypatch.setattr(analyze, "run_condition", lambda img, q, is_food: {
        "status": "not_assessed", "confidence": None, "model_status": "not_installed", "message": "No condition model."})
    yield state, monkeypatch
    app.dependency_overrides.clear()


def analyse(c=None):
    return (c or TestClient(app)).post("/api/analyze/food", files={"file": ("f.png", png("yellow"), "image/png")})


# ================================================================== freshness detection
def test_head_classifies_fresh_borderline_and_rotten_without_inventing_percentages():
    h = trained_head()
    out = {name: F.annotate(h.assess(x, "Apple", True)) for name, x in
           (("fresh", FRESH_FEATS), ("middle", MIDDLE_FEATS), ("rotten", ROTTEN_FEATS))}
    assert out["fresh"]["status"] == "fresh" and out["rotten"]["status"] == "possibly_spoiled"
    assert out["middle"]["status"] == "uncertain" and out["middle"]["confidence"] is None  # never forced into fresh/rotten
    assert out["middle"]["condition_label"] == "Borderline / unclear"
    for f in out.values():
        assert f["freshness_percent"] is None and f["deterioration_percent"] is None and f["percent_supported"] is False
        assert "not a freshness percentage" in f["percent_note"]


def test_head_does_not_assess_foods_it_was_not_trained_on():
    f = trained_head().assess(ROTTEN_FEATS, "Pizza", True)
    assert f["status"] == "not_assessed" and "not supported for Pizza" in f["message"]


def test_recognizer_without_installed_head_reports_not_installed_explicitly(tmp_path):
    rec = FoodRecognizer(model_dir=tmp_path)  # no TensorFlow needed: nothing is loaded
    f = rec.assess_freshness(ROTTEN_FEATS, "Apple")
    assert f["status"] == "not_assessed" and f["model_status"] == "not_installed" and "not installed" in f["message"]
    assert rec.assess_freshness(None, "Apple") is None  # no photo embedding at all


def test_rotten_food_is_reported_with_the_embedding_never_leaking_into_the_response(env):
    r = analyse()
    j = r.json()
    assert r.status_code == 200 and j["prediction"]["food"] == "Banana"
    assert j["freshness"]["status"] == "possibly_spoiled" and j["freshness"]["condition_label"] == "Rotten / possibly spoiled"
    assert "features" not in j and "features" not in r.text


def test_freshness_is_assessed_when_openai_confirms_a_low_score_result(env):
    state, _ = env
    state["rec"] = HeadRecognizer(FRESH_FEATS, food="Banana", score=0.55, decision="uncertain", reason="low_confidence")
    state["oa"] = openai_result("recognized", "Banana", "Banana", "Fruits")
    j = analyse().json()
    assert j["success"] and j["identification"]["verified_by"][:2] == ["SmartPlateAI image model", "OpenAI Vision"]
    assert j["freshness"]["status"] == "fresh"  # previously 'not_assessed', because the image model alone had not accepted it


def test_confirmed_candidate_gets_the_freshness_of_this_photo_for_that_food(env):
    state, _ = env
    state["rec"] = HeadRecognizer(ROTTEN_FEATS, food="Banana", score=0.5, decision="uncertain", reason="low_confidence")
    c = TestClient(app)
    low = analyse(c).json()
    assert low["error_code"] == "LOW_CONFIDENCE"
    apple = c.post("/api/analyze/confirm", json={"food": "Apple", "pending_id": low["pending_id"]}).json()
    assert apple["freshness"]["status"] == "possibly_spoiled" and apple["safety_alert"]["level"] == "danger"


# ================================================================== rotten-food precautions
def test_rotten_food_gets_a_do_not_eat_alert_and_no_consumption_advice(env):
    j = analyse().json()
    alert = j["safety_alert"]
    assert alert["level"] == "danger" and "do not eat" in alert["title"].lower()
    assert "does not apply to spoiled food" in alert["message"]
    texts = " ".join(p["text"] for p in j["precautions"]).lower()
    assert "do not eat this food" in texts and "do not cut away the spoiled part" in texts and "medical advice" in texts
    for consumption_advice in ("just before eating", "cut away bruised", "reheat", "cook thoroughly"):
        assert consumption_advice not in texts
    assert any(p["kind"] == "danger" for p in j["precautions"])


def test_spoiled_food_nutrition_is_the_unchanged_reference_and_is_labelled(env):
    j = analyse().json()
    assert j["nutrition"]["source_fdc_id"] == 173944  # banana reference, not lowered or altered for spoilage
    assert any("not lowered or changed" in n for n in j["notes"])


def test_borderline_food_gets_a_caution_and_fresh_food_no_alert(env):
    state, _ = env
    state["rec"] = HeadRecognizer(MIDDLE_FEATS, food="Banana", score=0.95)
    mid = analyse().json()
    assert mid["safety_alert"]["level"] == "caution" and "when in doubt, throw it out" in mid["safety_alert"]["message"].lower()
    assert any(p["kind"] == "warning" and "could not be judged" in p["text"] for p in mid["precautions"])
    state["rec"] = HeadRecognizer(FRESH_FEATS, food="Banana", score=0.95)
    fresh = analyse().json()
    assert fresh["safety_alert"] is None and fresh["freshness"]["status"] == "fresh"
    assert any("does not prove the food is safe" in p["text"] for p in fresh["precautions"])


def test_spoilage_precautions_never_recommend_eating():
    items = precautions.for_food("Tomato", {"status": "possibly_spoiled"})
    assert items == precautions.spoilage_precautions()
    assert precautions.safety_alert({"status": "not_assessed"}) is None and precautions.safety_alert(None) is None


# ================================================================== automatic results vs. confirmation
def test_classifier_disagreement_resolved_by_openai_is_shown_without_confirmation(env):
    state, _ = env
    state["rec"] = HeadRecognizer(FRESH_FEATS, food="Banana", score=0.62, decision="uncertain", reason="classifier_disagreement")
    state["oa"] = openai_result("recognized", "Banana", "Banana", "Fruits")
    j = analyse().json()
    assert j["success"] and j["recognition"]["status"] == "verified_both" and j["prediction"]["food"] == "Banana"


def test_classifier_disagreement_with_a_different_openai_food_still_asks(env):
    state, _ = env
    state["rec"] = HeadRecognizer(FRESH_FEATS, food="Banana", score=0.62, decision="uncertain", reason="classifier_disagreement")
    state["oa"] = openai_result("recognized", "Apple", "Apple", "Fruits")
    j = analyse().json()
    assert j["error_code"] == "LOW_CONFIDENCE" and j["requires_confirmation"] and "nutrition" not in j


def test_low_score_without_any_second_opinion_still_asks(env):
    state, _ = env
    state["rec"] = HeadRecognizer(FRESH_FEATS, food="Banana", score=0.5, decision="uncertain", reason="low_confidence")
    state["oa"] = {"status": "unavailable", "reason": "not_configured"}
    assert analyse().json()["error_code"] == "LOW_CONFIDENCE"


# ================================================================== food-specific nutrition
@pytest.mark.parametrize("food,fdc,kcal", [("Banana", 173944, 89.0), ("Apple", 171688, 52.0)])
def test_nutrition_belongs_to_the_identified_food(env, food, fdc, kcal):
    state, _ = env
    state["rec"] = HeadRecognizer(FRESH_FEATS, food=food, score=0.95)
    j = analyse().json()
    vals = {n["key"]: n["per_100g"] for n in j["nutrition"]["nutrients"]}
    assert j["prediction"]["food"] == food and j["nutrition"]["source_fdc_id"] == fdc and vals["energy_kcal"] == kcal


def test_supported_food_missing_from_the_reference_gets_no_substitute_values(env):
    state, _ = env
    state["rec"] = HeadRecognizer(FRESH_FEATS, food="Tomato", score=0.95)  # Tomato is not in the fixture CSV
    j = analyse().json()
    assert j["success"] and j["nutrition"] is None and j["nutrition_error"]


def test_food_outside_the_classes_uses_usda_for_that_exact_name_only(env):
    state, mp = env
    state["rec"] = HeadRecognizer(FRESH_FEATS, food="Tomato", score=0.3, decision="unsupported_food", reason="far_from_supported_foods")
    state["oa"] = openai_result("unsupported_food", "Kiwi", None, "Fruits")
    asked = []

    def fake_usda(food, category, grams=None):
        asked.append(food)
        return {"status": "no_match", "message": f"No verified USDA reference record clearly matches '{food}', so nutrition is not shown."}
    mp.setattr(usda, "lookup", fake_usda)
    j = analyse().json()
    assert j["prediction"]["food"] == "Kiwi" and asked == ["Kiwi"]
    assert j["nutrition"] is None and "Kiwi" in j["nutrition_error"]  # never Tomato's (or any other food's) values


# ================================================================== unknown packaged products
@pytest.fixture
def pk(monkeypatch, tmp_path):
    state = {"data": dataset(tmp_path)}
    app.dependency_overrides[packaged_route.get_packaged_data] = lambda: state["data"]
    monkeypatch.setattr(packaged_route, "run_ocr", lambda img: {"text": BACK.replace("Masala Tastemaker", "Seasoning"),
                                                                "confidence": 85.0, "word_count": 40, "rotation": 0, "quality": "good"})
    monkeypatch.setattr(packaged_route, "run_barcode", lambda img: {"status": "not_found"})
    monkeypatch.setattr(packaged_route, "run_package_reading", lambda f, b: {"status": "unavailable", "reason": "not_configured"})
    monkeypatch.setattr(off, "enabled", lambda: True)
    monkeypatch.setattr(off, "by_barcode", lambda code: {"status": "not_found", "barcode": code, "message": "Not in Open Food Facts."})
    monkeypatch.setattr(off, "search", lambda name, brand=None, verify_text=None: {"status": "not_found", "candidates": [],
                                                                                   "message": "Open Food Facts has no product for this search."})
    yield monkeypatch
    app.dependency_overrides.clear()


def scan(front_text: str, prominent: list[str], mp):
    mp.setattr(packaged_route, "run_front_ocr", lambda img: {"text": front_text, "prominent": prominent})
    return TestClient(app).post("/api/analyze/packaged", files={"front": ("f.png", png("blue"), "image/png"),
                                                                "back": ("b.png", png("white"), "image/png")}).json()


def test_unknown_brand_is_not_given_another_products_record_or_nutrition(pk):
    j = scan("ZORBO\nMillet Crunch Puffs\nPeri Peri", ["ZORBO", "Millet", "Crunch", "Puffs"], pk)
    assert j["success"] and j["product"] is None and j["match"]["status"] != "matched"
    assert j["identification"]["status"] in ("unidentified", "candidates") and j["identification"]["name"] is None
    assert j["external"]["status"] == "not_found"
    # what the pack itself says is still returned, attributed to the label
    rows = {r["key"]: r for r in j["label_nutrition"]["rows"]}
    assert rows["energy_kcal"]["value"] == 427 and rows["energy_kcal"]["source"].startswith("package label")
    assert any("could not be identified" in w for w in j["warnings"])


def test_unknown_product_sharing_generic_words_does_not_match_a_dataset_noodle(pk):
    j = scan("CHINGS SECRET\nSchezwan Instant Noodles", ["CHINGS", "SECRET", "Schezwan", "Noodles"], pk)
    assert j["product"] is None and j["match"]["status"] != "matched"
    assert all("Maggi" not in (c.get("name") or "") for c in j["match"]["candidates"])  # 'noodles' alone is not evidence


def test_open_food_facts_result_for_an_unknown_product_is_used_only_when_the_label_confirms_it(pk):
    seen = {}

    def fake_search(name, brand=None, verify_text=None):
        seen["verify"] = verify_text
        return {"status": "unconfirmed", "candidates": [{"code": "0000000000000", "name": "Other Puffs", "brand": "Elsewhere"}],
                "message": "Open Food Facts results did not match the brand and name read from the pack."}
    pk.setattr(off, "search", fake_search)
    j = scan("ZORBO\nMillet Crunch Puffs", ["ZORBO", "Millet", "Crunch", "Puffs"], pk)
    assert "ZORBO" in seen["verify"]  # the external result is checked against the pack text
    assert j["identification"]["status"] != "identified" and j["product"] is None
