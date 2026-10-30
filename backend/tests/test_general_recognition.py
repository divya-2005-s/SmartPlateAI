"""General (outside-the-24-classes) recognition through OpenAI, USDA nutrition matching for those foods, packaged-product
routing and OpenAI failure handling.

OpenAI and USDA are MOCKED (no network or paid calls). The USDA candidate descriptions below are the real record
descriptions returned by FoodData Central on 2026-10-15 for these queries, so the ranking is tested against real USDA
naming; the nutrient values are placeholders. These tests do not measure real-world recognition accuracy: no real photos
of milk, paneer, dosa etc. were available, and the OpenAI account had no credit at the time."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes import analyze
from app.main import app
from app.services import openai_vision, usda, vision
from tests.test_freshness_nutrition_quality import RealishNutrition, ref  # noqa: F401  (fixture)
from tests.test_freshness_safety_automatic import FRESH_FEATS, ROTTEN_FEATS, HeadRecognizer
from tests.test_recognition_packaged_history_fixes import png
from tests.test_recognition_packaged_history_fixes import oa as openai_result

F, S, N = "Foundation", "SR Legacy", "Survey (FNDDS)"
REAL_CANDIDATES = {  # query -> (dataType, description) in the order USDA returned them
    "milk": [(N, "Coconut milk"), (S, "Crackers, milk"), (N, "Crackers, milk"), (N, "Goat milk"), (N, "Milk, human"),
             (N, "Milk, malted"), (N, "Milk, NFS"), (N, "Milk, whole"), (N, "Oat milk"), (N, "Rice milk")],
    "paneer": [(N, "Palak Paneer"), (N, "Cheese, paneer")],
    "cheese": [(N, "Cheese, processed cheese food"), (N, "Cheese spread, cream cheese"), (S, "Cheese spread, cream cheese base"),
               (N, "Cheese, Monterey"), (N, "Cheese ball"), (N, "Cheese, paneer"), (N, "Crackers, cheese"), (N, "Head cheese"),
               (N, "Cheese, NFS")],
    "yogurt": [(S, "Tofu yogurt"), (N, "Yogurt tube"), (N, "Yogurt, liquid"), (N, "Yogurt, NFS"), (N, "Yogurt, soy"),
               (N, "Frozen yogurt, NFS")],
    "butter": [(S, "Butter, Clarified butter (ghee)"), (N, "Fruit butter"), (N, "Butter, tub"), (N, "Almond butter"),
               (N, "Butter, NFS"), (S, "Butter, salted"), (N, "Peanut butter")],
    "egg": [(F, "Eggs, Grade A, Large, egg white"), (F, "Eggs, Grade A, Large, egg whole"), (F, "Eggs, Grade A, Large, egg yolk"),
            (N, "Egg, Benedict"), (N, "Egg, deviled"), (S, "Bagels, egg"), (S, "Bread, egg"), (N, "Egg burrito")],
    "rice": [(N, "Dirty rice"), (N, "Rice dressing"), (N, "Crackers, rice"), (N, "Rice pilaf"), (N, "Rice cake"), (N, "Bread, rice"),
             (N, "Rice, cooked, NFS"), (N, "Rice, fried, NFS"), (N, "Rice, fried, meatless")],
    "cooked white rice": [(N, "Rice, white, cooked, glutinous"), (N, "Rice, white, cooked, made with oil"),
                          (N, "Rice, white, cooked, no added fat"), (N, "Rice, white, cooked, NS as to fat"),
                          (S, "Rice, white, glutinous, unenriched, cooked")],
    "dal": [(N, "Dal")],
    "idli": [(N, "Idli")],
    "dosa": [(N, "Dosa, with filling"), (N, "Dosa, plain")],
    "chapati": [(S, "Bread, chapati or roti, plain, commercially prepared"),
                (S, "Bread, chapati or roti, whole wheat, commercially prepared, frozen")],
    "roti": [(N, "Bread, chappatti or roti"), (S, "Bread, chapati or roti, plain, commercially prepared"),
             (S, "Bread, chapati or roti, whole wheat, commercially prepared, frozen")],
    "kiwi raw": [(N, "Kiwi fruit, raw"), (F, "Kiwifruit (kiwi), green, peeled, raw"), (S, "Beverages, Kiwi Strawberry Juice Drink")],
    "jackfruit raw": [(S, "Jackfruit, raw"), (S, "Jackfruit, canned, syrup pack")],
}


def fake_usda(monkeypatch, calls=None):
    monkeypatch.setattr(usda, "enabled", lambda: True)
    monkeypatch.setattr(usda, "get_settings", lambda: SimpleNamespace(usda_fdc_api_key="k"))
    monkeypatch.setattr(usda, "cache_get", lambda k: None)
    monkeypatch.setattr(usda, "cache_set", lambda *a: None)

    def request_json(url, method="GET", payload=None, **kw):
        q = payload["query"].lower()
        if calls is not None:
            calls.append(q)
        foods = [{"fdcId": 1000 + i, "description": d, "dataType": t, "foodNutrients": [
            {"nutrientName": "Energy", "unitName": "KCAL", "value": 50.0 + i}, {"nutrientName": "Protein", "unitName": "G", "value": 3.0}]}
            for i, (t, d) in enumerate(REAL_CANDIDATES.get(q, []))]
        return {"foods": foods}
    monkeypatch.setattr(usda, "request_json", request_json)


# ================================================================== USDA: the record must BE the identified food
@pytest.mark.parametrize("food,category,expected", [
    ("Milk", "Dairy", "Milk, NFS"),                    # not "Crackers, milk" / "Coconut milk"
    ("Paneer", "Dairy", "Cheese, paneer"),             # not "Palak Paneer"
    ("Cheese", "Dairy", "Cheese, NFS"),
    ("Yogurt", "Dairy", "Yogurt, NFS"),                # not "Tofu yogurt"
    ("Curd", "Dairy", "Yogurt, NFS"),                  # Indian curd is yogurt (lookup vocabulary only)
    ("Butter", "Dairy", "Butter, NFS"),                # not ghee
    ("Egg", "Meat, Fish & Eggs", "Eggs, Grade A, Large, egg whole"),  # not the white or yolk alone
    ("Cooked white rice", "Grains & Cereals", "Rice, white, cooked, NS as to fat"),
    ("Dal", "Cooked Dishes", "Dal"),
    ("Idli", "Cooked Dishes", "Idli"),
    ("Dosa", "Cooked Dishes", "Dosa, plain"),
    ("Chapati", "Bakery Items", "Bread, chapati or roti, plain, commercially prepared"),
    ("Roti", "Bakery Items", "Bread, chapati or roti, plain, commercially prepared"),
    ("Kiwi", "Fruits", "Kiwi fruit, raw"),
    ("Jackfruit", "Fruits", "Jackfruit, raw"),         # not in any list in the code: general, not a whitelist
])
def test_usda_picks_the_record_that_is_the_identified_food(monkeypatch, food, category, expected):
    fake_usda(monkeypatch)
    got = usda.lookup(food, category, serving_grams=200)
    assert got["status"] == "found" and got["nutrition"]["matched_description"] == expected
    assert got["nutrition"]["basis"].startswith("per 100 g by weight")
    energy = next(n for n in got["nutrition"]["nutrients"] if n["key"] == "energy_kcal")
    assert energy["per_serving"] == pytest.approx(energy["per_100g"] * 2)


def test_ambiguous_generic_name_gets_no_nutrition_rather_than_a_guess(monkeypatch):
    fake_usda(monkeypatch)
    got = usda.lookup("Rice", "Grains & Cereals")  # cooked vs fried rice differ a lot
    assert got["status"] == "no_match" and got.get("ambiguous") and "specific type" in got["message"]


def test_unknown_food_gets_no_substitute_and_missing_nutrients_stay_missing(monkeypatch):
    fake_usda(monkeypatch)
    assert usda.lookup("Masala dosa", "Cooked Dishes")["status"] == "no_match"  # no record names it: nothing shown
    got = usda.lookup("Dal", "Cooked Dishes")
    vals = {n["key"]: n for n in got["nutrition"]["nutrients"]}
    assert vals["dietary_fibre_g"]["per_100g"] is None and "Dietary fibre" in got["nutrition"]["not_available"]
    assert "standard recipe" in got["nutrition"]["note"]  # FNDDS records are labelled as recipe-based


# ================================================================== routing with OpenAI (mocked)
@pytest.fixture
def env(monkeypatch, ref):  # noqa: F811
    state = {"rec": HeadRecognizer(FRESH_FEATS, food="Tomato", score=0.3, decision="unsupported_food", reason="far_from_supported_foods"),
             "oa": openai_result("unsupported_food", "Milk", None, "Dairy"), "calls": 0}
    app.dependency_overrides[analyze.get_recognizer] = lambda: state["rec"]
    app.dependency_overrides[analyze.get_nutrition] = lambda: RealishNutrition(ref)
    monkeypatch.setattr(vision, "enabled", lambda: False)
    monkeypatch.setattr(openai_vision, "availability", lambda: "ready")

    def identify(img, classes):
        state["calls"] += 1
        if isinstance(state["oa"], Exception):
            raise state["oa"]
        return state["oa"]
    monkeypatch.setattr(openai_vision, "identify", identify)
    monkeypatch.setattr(analyze, "run_condition", lambda img, q, is_food: {
        "status": "not_assessed", "confidence": None, "model_status": "not_installed", "message": "No condition model."})
    fake_usda(monkeypatch)
    yield state
    app.dependency_overrides.clear()


def analyse(c=None):
    return (c or TestClient(app)).post("/api/analyze/food", files={"file": ("f.png", png("white"), "image/png")}).json()


@pytest.mark.parametrize("name,category,record", [
    ("Milk", "Dairy", "Milk, NFS"), ("Paneer", "Dairy", "Cheese, paneer"), ("Curd", "Dairy", "Yogurt, NFS"),
    ("Cooked white rice", "Grains & Cereals", "Rice, white, cooked, NS as to fat"), ("Dosa", "Cooked Dishes", "Dosa, plain"),
    ("Jackfruit", "Fruits", "Jackfruit, raw"),
])
def test_foods_outside_the_24_classes_are_identified_with_their_own_nutrition(env, name, category, record):
    env["oa"] = openai_result("unsupported_food", name, None, category)
    j = analyse()
    assert j["success"] and j["prediction"]["food"] == name and j["prediction"]["class_id"] is None
    assert j["identification"]["source"] == "openai" and j["identification"]["verified_by"] == ["OpenAI Vision"]
    assert j["prediction"]["confidence"] is None and j["acceptance_basis"] == "openai_identification_without_score"
    assert j["requires_confirmation"] is False and j["nutrition"]["matched_description"] == record
    assert j["freshness"]["status"] == "not_assessed" and "not supported for" in j["freshness"]["message"]


def test_low_score_class_guess_does_not_override_a_clear_openai_identification(env):
    env["rec"] = HeadRecognizer(FRESH_FEATS, food="Potato", score=0.62) if "Potato" in HeadRecognizer.class_names else \
        HeadRecognizer(FRESH_FEATS, food="Tomato", score=0.62)  # model's own verdict: accept, but below 70%
    env["oa"] = openai_result("unsupported_food", "Paneer", None, "Dairy")
    j = analyse()
    assert j["success"] and j["prediction"]["food"] == "Paneer" and j["nutrition"]["matched_description"] == "Cheese, paneer"


def test_high_score_class_vs_openai_other_food_asks_and_offers_openai_first(env):
    env["rec"] = HeadRecognizer(FRESH_FEATS, food="Tomato", score=0.92)
    env["oa"] = openai_result("unsupported_food", "Paneer", None, "Dairy")
    j = analyse()
    assert j["error_code"] == "LOW_CONFIDENCE" and j["reason"] == "openai_unsupported_food"
    assert j["general_candidate"]["food"] == "Paneer" and "nutrition" not in j


def test_confirming_the_openai_suggestion_keeps_its_nutrition_and_photo(env):
    env["rec"] = HeadRecognizer(ROTTEN_FEATS, food="Tomato", score=0.92)
    env["oa"] = openai_result("unsupported_food", "Paneer", None, "Dairy")
    c = TestClient(app)
    low = analyse(c)
    calls = env["calls"]
    j = c.post("/api/analyze/confirm", json={"food": "Paneer", "pending_id": low["pending_id"]}).json()
    assert j["identification"]["source"] == "user_confirmed" and j["nutrition"]["matched_description"] == "Cheese, paneer"
    assert "not supported for Paneer" in j["freshness"]["message"]  # never forced into fresh/rotten
    assert env["calls"] == calls  # confirmation makes no new OpenAI call


def test_supported_food_uses_one_openai_call_and_assesses_freshness(env):
    env["rec"] = HeadRecognizer(ROTTEN_FEATS, food="Apple", score=0.97)
    env["oa"] = openai_result("recognized", "Apple", "Apple", "Fruits")
    j = analyse()
    assert j["success"] and j["identification"]["source"] == "image_model_and_openai" and env["calls"] == 1
    assert j["freshness"]["status"] == "possibly_spoiled" and j["safety_alert"]["level"] == "danger"


def test_openai_unsure_or_no_food_is_not_turned_into_a_class(env):
    env["oa"] = openai_result("uncertain", None, None, None)
    j = analyse()
    assert j["error_code"] in ("UNSUPPORTED_FOOD", "LOW_CONFIDENCE") and "prediction" not in j
    env["rec"] = HeadRecognizer(FRESH_FEATS, food="Tomato", score=0.2, decision="non_food", reason="far_from_supported_foods")
    env["oa"] = {"status": "no_food", "food_name": None, "supported_food": None, "visible_evidence": [], "uncertainty": None, "category": None}
    assert analyse()["error_code"] == "NON_FOOD_IMAGE"


@pytest.mark.parametrize("code", ["timeout", "rate_limited", "quota_exhausted", "provider_error"])
def test_openai_failure_never_labels_an_unsupported_food_as_a_class(env, code):
    env["oa"] = openai_vision.OpenAIVisionError(code)
    j = analyse()  # image model: "not one of my foods"
    assert j["error_code"] == "UNSUPPORTED_FOOD" and "prediction" not in j and j["openai_vision"]["reason"] == code


def test_quota_exhaustion_is_explained(env):
    env["rec"] = HeadRecognizer(FRESH_FEATS, food="Apple", score=0.95)
    env["oa"] = openai_vision.OpenAIVisionError("quota_exhausted")
    j = analyse()
    assert j["success"] and "no remaining credit" in j["recognition"]["message"] and "24 foods" in j["recognition"]["message"]


def test_rate_limit_and_exhausted_credit_are_told_apart():
    def exc(body, code=None):
        return SimpleNamespace(body=body, code=code)
    assert openai_vision.rate_limit_reason(exc({"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted"}})) == "quota_exhausted"
    assert openai_vision.rate_limit_reason(exc({"type": "insufficient_quota"})) == "quota_exhausted"
    assert openai_vision.rate_limit_reason(exc({"error": {"type": "requests", "code": "rate_limit_exceeded"}})) == "rate_limited"
    assert openai_vision.rate_limit_reason(exc(None)) == "rate_limited"


def test_packaged_product_photo_is_sent_to_the_packaged_scanner(env, monkeypatch):
    calls = []
    env["oa"] = openai_result("unsupported_food", "Instant noodles packet", None, "Packaged Food")
    fake_usda(monkeypatch, calls)
    j = analyse()
    assert j["success"] and j["suggest_packaged_scan"] is True
    assert j["nutrition"] is None and "Scan packaged food" in j["nutrition_error"] and calls == []  # no generic record used


def test_prompt_asks_for_specific_names_without_guessing():
    assert "preparation state" in openai_vision.PROMPT and "never guess" in openai_vision.PROMPT
    assert "confidence" in openai_vision.PROMPT.lower()  # still tells the provider not to invent a confidence value
