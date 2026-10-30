"""Tests for the recognition, packaged front/back, barcode, history-persistence, report and chat-format fixes.
Every external provider (OpenAI, Google Vision, USDA, Open Food Facts, Tesseract) is mocked; no network or paid calls."""
import io
import json
import socket
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.routes import analyze, packaged as packaged_route
from app.core.db import connect
from app.main import app
from app.services import analysis_store, chat, food_category, http, openai_vision, usda, vision
from app.services import auth as auth_store
from app.services import openfoodfacts as off

CLASSES = ["Apple", "Banana", "Tomato", "Onion"]


# ------------------------------------------------------------------ fakes
class FakeRecognizer:
    status_message = "ready"
    class_names = CLASSES

    def __init__(self, decision="accept", food="Tomato", reason=None, score=0.829):
        self.decision, self.food, self.reason, self.score = decision, food, reason, score

    def load(self):
        return True

    def analyze_image(self, img):
        top = [{"class_id": CLASSES.index(self.food), "food": self.food, "score": self.score},
               {"class_id": 0, "food": "Apple", "score": 0.08}]
        return {"decision": self.decision, "reason": self.reason, "calibrated": True, "confidence": self.score, "margin": 0.7,
                "top_k": top, "signals": {}, "freshness": {"status": "not_assessed", "confidence": None, "message": "Not assessed."}}


class FakeNutrition:
    error = None

    def lookup(self, food, serving=None):
        if food not in CLASSES:
            return None
        return {"basis": "per 100 g", "source_fdc_id": 1, "nutrients": [
            {"key": "energy_kcal", "label": "Energy", "unit": "kcal", "per_100g": 18.0, "per_serving": None}], "not_available": []}


def oa(status="unsupported_food", food="Red Onion", supported=None, category="Vegetables"):
    return {"status": status, "food_name": food, "supported_food": supported, "visible_evidence": ["purple-red papery bulb"],
            "uncertainty": None, "category": category}


def png(color="red"):
    b = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(b, "PNG")
    return b.getvalue()


USDA_ONION = {"status": "found", "nutrition": {
    "basis": "per 100 g (USDA FoodData Central Foundation: Onions, red, raw)", "source_fdc_id": 790577, "is_estimate": True, "note": "x",
    "serving_grams": None, "serving_note": "x", "not_available": [],
    "nutrients": [{"key": "energy_kcal", "label": "Energy", "unit": "kcal", "per_100g": 44.0, "per_serving": None}]}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_store, "DB_PATH", tmp_path / "users.db")
    rec = FakeRecognizer()
    app.dependency_overrides[analyze.get_recognizer] = lambda: rec
    app.dependency_overrides[analyze.get_nutrition] = lambda: FakeNutrition()
    monkeypatch.setattr(vision, "enabled", lambda: False)
    monkeypatch.setattr(openai_vision, "availability", lambda: "ready")
    monkeypatch.setattr(openai_vision, "identify", lambda img, classes: oa())
    monkeypatch.setattr(usda, "lookup", lambda food, cat, grams=None: USDA_ONION if "onion" in food.lower() else
                        {"status": "no_match", "message": f"No verified USDA reference record clearly matches '{food}'."})
    yield SimpleNamespace(rec=rec, mp=monkeypatch)
    app.dependency_overrides.clear()


def cookie_client():
    c = TestClient(app)
    r = c.post("/api/auth/signup", json={"email": f"u{uuid.uuid4().hex[:8]}@example.com", "password": "correct horse battery"})
    assert r.status_code == 201 and "smartplate_session" in r.headers.get("set-cookie", "")
    return c


def analyse(c, key=None):
    return c.post("/api/analyze/food", files={"file": ("food.png", png(), "image/png")},
                  headers={"Idempotency-Key": key} if key else {})


# ================================================================== recognition
def test_red_onion_with_tomato_from_model_asks_user_and_offers_onion(env):
    body = analyse(TestClient(app)).json()
    assert body["error_code"] == "LOW_CONFIDENCE" and body["reason"] == "openai_unsupported_food"
    assert body["candidates"][0]["food"] == "Tomato"  # the model's answer is shown only as a candidate
    assert body["general_candidate"] == {"food": "Red Onion", "category": "Vegetables", "source": "OpenAI Vision",
                                         "note": "Not one of the 24 foods the image model was trained on."}
    assert "nutrition" not in body and body["pending_id"]


def test_user_can_confirm_the_openai_suggestion_outside_the_classes(env):
    c = TestClient(app)
    body = analyse(c).json()
    r = c.post("/api/analyze/confirm", json={"food": "Red Onion", "pending_id": body["pending_id"]}).json()
    assert r["success"] and r["identification"]["food"] == "Red Onion" and r["identification"]["source"] == "user_confirmed"
    assert r["identification"]["category"] == "Vegetables" and r["nutrition"]["source_fdc_id"] == 790577
    # Without the photo's pending id, the same typed name is a manual selection rather than an OpenAI-confirmed suggestion.
    manual = c.post("/api/analyze/confirm", json={"food": "Red Onion"}).json()
    assert manual["success"] and manual["identification"]["source"] == "user_selected"
    assert manual["identification"]["verified_by"] == ["You"]
    assert c.post("/api/analyze/confirm", json={"food": "Durian", "pending_id": body["pending_id"]}).json()["identification"]["source"] == "user_selected"


@pytest.mark.parametrize("tf_decision", ["unsupported_food", "non_food", "uncertain"])
def test_food_outside_the_24_classes_is_identified_when_model_does_not_claim_a_class(env, tf_decision):
    env.rec.decision = tf_decision
    body = analyse(TestClient(app)).json()
    assert body["success"] is True and body["prediction"]["food"] == "Red Onion" and body["prediction"]["confidence"] is None
    ident = body["identification"]
    assert ident["category"] == "Vegetables" and ident["source"] == "openai" and ident["supported_class"] is None
    assert ident["verified_by"] == ["OpenAI Vision"]  # no false claim that the image model agreed
    assert body["recognition"]["status"] == "openai_identified"
    assert body["nutrition"]["basis"].startswith("per 100 g (USDA") and body["freshness"]["status"] == "not_assessed"


def test_outside_food_without_verified_nutrition_shows_identification_only(env):
    env.rec.decision = "unsupported_food"
    env.mp.setattr(openai_vision, "identify", lambda img, classes: oa(food="Durian", category="Fruits"))
    body = analyse(TestClient(app)).json()
    assert body["success"] and body["identification"]["food"] == "Durian" and body["identification"]["category"] == "Fruits"
    assert body["nutrition"] is None and "No verified USDA" in body["nutrition_error"]


def test_apple_agreement_is_verified_by_both_with_category(env):
    env.rec.food, env.rec.score = "Apple", 0.95
    env.mp.setattr(openai_vision, "identify", lambda img, classes: oa("recognized", "Apple", "Apple", "Fruits"))
    body = analyse(TestClient(app)).json()
    assert body["success"] and body["recognition"]["status"] == "verified_both"
    assert body["identification"]["category"] == "Fruits"
    assert body["identification"]["verified_by"] == ["SmartPlateAI image model", "OpenAI Vision"]


def test_openai_failure_with_google_vision_agreement_is_accepted_and_labelled(env):
    env.mp.setattr(openai_vision, "identify", lambda img, classes: (_ for _ in ()).throw(openai_vision.OpenAIVisionError("network_error")))
    env.mp.setattr(vision, "enabled", lambda: True)
    env.mp.setattr(vision, "annotate", lambda img: {"labels": [{"name": "Tomato", "score": 0.95}], "objects": []})
    body = analyse(TestClient(app)).json()
    assert body["success"] and "Google Vision agrees" in body["recognition"]["message"]
    assert body["identification"]["verified_by"] == ["SmartPlateAI image model", "Google Vision"]


def test_openai_missing_key_falls_back_to_image_model_clearly_labelled(env):
    env.mp.setattr(openai_vision, "availability", lambda: "not_configured")
    body = analyse(TestClient(app)).json()
    assert body["success"] and body["recognition"]["status"] == "tensorflow_fallback"
    assert body["identification"]["verified_by"] == ["SmartPlateAI image model"]


def test_qualifier_aware_class_matching_does_not_merge_different_foods():
    m = openai_vision.class_for_name
    assert m("Red Onion", CLASSES) == "Onion" and m("ripe bananas", CLASSES) == "Banana" and m("Tomatoes", CLASSES) == "Tomato"
    assert m("Sweet Potato", ["Potato"]) is None and m("Pineapple", CLASSES) is None and m("Apple pie", CLASSES) is None
    payload = SimpleNamespace(output_text=json.dumps({"food_name": "Red Onion", "supported_food": "Onion", "visible_evidence": ["bulb"],
                                                      "contains_food": True, "uncertainty": None, "category": "Vegetables"}))
    parsed = openai_vision._parse_output(payload, CLASSES)
    assert parsed["status"] == "recognized" and parsed["supported_food"] == "Onion" and parsed["category"] == "Vegetables"
    bad_cat = SimpleNamespace(output_text=json.dumps({"food_name": "Apple", "supported_food": "Apple", "visible_evidence": [],
                                                      "contains_food": True, "uncertainty": None, "category": "Poison"}))
    assert openai_vision._parse_output(bad_cat, CLASSES)["category"] is None


def test_categories_are_not_fresh_food():
    r = food_category.resolve
    assert r("Red Onion") == "Vegetables" and r("Apple") == "Fruits" and r("Apple juice") == "Beverages"
    assert r("Potato chips") == "Snacks" and r("Masala dosa") == "Cooked Dishes" and r("Eggplant") == "Vegetables"
    assert r("Mystery item") == "Other" and r("Taco", "Cooked Dishes") == "Cooked Dishes" and r("Apple", "Fresh food") == "Fruits"


# ================================================================== USDA matching
def test_usda_accepts_only_clear_raw_reference_matches():
    assert usda.accept("Onions, red, raw", "Foundation", "Red Onion", produce=True)
    assert not usda.accept("Onions, cooked, boiled, drained, with salt", "SR Legacy", "Red Onion", produce=True)
    assert not usda.accept("Tomatoes, red, ripe, raw", "Foundation", "Red Onion", produce=True)
    assert not usda.accept("ONION RINGS", "Branded", "Onion", produce=False)
    assert usda.accept("Bread, white, commercially prepared", "SR Legacy", "White bread", produce=False)


def test_usda_lookup_maps_units_and_never_substitutes(monkeypatch):
    monkeypatch.setattr(usda, "enabled", lambda: True)
    monkeypatch.setattr(usda, "get_settings", lambda: SimpleNamespace(usda_fdc_api_key="k"))
    monkeypatch.setattr(usda, "cache_get", lambda k: None)
    monkeypatch.setattr(usda, "cache_set", lambda *a: None)
    foods = {"foods": [
        {"fdcId": 1, "description": "Onions, cooked, boiled", "dataType": "SR Legacy", "foodNutrients": []},
        {"fdcId": 790577, "description": "Onions, red, raw", "dataType": "Foundation", "foodNutrients": [
            {"nutrientName": "Energy", "unitName": "kJ", "value": 184}, {"nutrientName": "Energy", "unitName": "KCAL", "value": 44},
            {"nutrientName": "Protein", "unitName": "G", "value": 0.94}, {"nutrientName": "Sodium, Na", "unitName": "MG", "value": 1}]}]}
    monkeypatch.setattr(usda, "request_json", lambda url, **kw: foods)
    got = usda.lookup("Red Onion", "Vegetables", serving_grams=50)
    vals = {n["key"]: n for n in got["nutrition"]["nutrients"]}
    assert got["status"] == "found" and got["nutrition"]["source_fdc_id"] == 790577
    assert vals["energy_kcal"]["per_100g"] == 44 and vals["energy_kcal"]["per_serving"] == 22
    assert vals["dietary_fibre_g"]["per_100g"] is None and "Dietary fibre" in got["nutrition"]["not_available"]
    monkeypatch.setattr(usda, "request_json", lambda url, **kw: {"foods": foods["foods"][:1]})
    assert usda.lookup("Purple Onion", "Vegetables")["status"] == "no_match"
    monkeypatch.setattr(usda, "enabled", lambda: False)
    assert usda.lookup("Red Onion", "Vegetables")["status"] == "unavailable"


# ================================================================== barcode
OFF_OK = {"status": 1, "product": {"code": "0012345678905", "product_name": "Oat Biscuits", "brands": "Sunbake",
                                   "nutriments": {"energy-kcal_100g": 480, "sodium_100g": 0.3}, "allergens_tags": ["en:gluten"]}}


@pytest.fixture
def barcode(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_store, "DB_PATH", tmp_path / "users.db")
    monkeypatch.setattr(off, "enabled", lambda: True)
    monkeypatch.setattr(off, "cache_get", lambda k: None)
    monkeypatch.setattr(off, "cache_set", lambda *a: None)
    return monkeypatch


def test_barcode_found_is_success_and_keeps_leading_zeros(barcode):
    seen = []

    def fake(url, **kw):
        seen.append(url)
        return OFF_OK
    barcode.setattr(off, "request_json", fake)
    r = TestClient(app).get("/api/packaged/off/012345678905")  # UPC-A with a leading zero
    j = r.json()
    assert r.status_code == 200 and j["success"] is True and j["product"]["name"] == "Oat Biscuits"
    assert "/product/012345678905.json" in seen[0] and j["barcode"] == "012345678905" and j["format"] == "UPC-A"
    assert j["history"] == {"saved": False, "reason": "not_signed_in", "message": "Sign in to save analyses to your history automatically."}


@pytest.mark.parametrize("raw,fake,status,code", [
    ("8901234567891", None, 422, "INVALID_BARCODE"),
    ("12345", None, 422, "INVALID_BARCODE"),
    ("012345678905", {"status": 0, "status_verbose": "product not found"}, 404, "PRODUCT_NOT_FOUND"),
    ("012345678905", http.ExternalError("TIMEOUT", "slow"), 504, "LOOKUP_TIMEOUT"),
    ("012345678905", http.ExternalError("RATE_LIMITED", "slow", 429), 429, "LOOKUP_RATE_LIMITED"),
    ("012345678905", http.ExternalError("UNREACHABLE", "down"), 503, "LOOKUP_UNAVAILABLE"),
    ("012345678905", ["not", "a", "dict"], 502, "LOOKUP_BAD_RESPONSE"),
])
def test_barcode_failures_use_real_status_and_error_code(barcode, raw, fake, status, code):
    def respond(url, **kw):
        if isinstance(fake, Exception):
            raise fake
        return fake
    barcode.setattr(off, "request_json", respond)
    r = TestClient(app).get(f"/api/packaged/off/{raw}")
    j = r.json()
    # The old endpoint returned HTTP 200 + success:false without error_code ("unexpected response (HTTP 200)").
    assert r.status_code == status and j["success"] is False and j["error_code"] == code and j["message"]


def test_upce_is_expanded_and_successful_barcode_is_saved_for_cookie_user(barcode):
    seen = []
    barcode.setattr(off, "request_json", lambda url, **kw: seen.append(url) or {
        "status": 1, "product": {**OFF_OK["product"], "code": "042100005264"}})
    c = cookie_client()
    j = c.get("/api/packaged/off/04252614").json()
    assert j["format"] == "UPC-E" and "/product/042100005264.json" in seen[0]
    assert j["history"]["saved"] is True
    hist = c.get("/api/history").json()
    assert hist["total"] == 1 and hist["items"][0]["title"] == "Sunbake Oat Biscuits"
    assert hist["items"][0]["summary"]["nutrition"]["per_100g"]["sodium_mg"] == 300.0


def test_http_helper_distinguishes_timeout(monkeypatch):
    def slow(*a, **k):
        raise socket.timeout("timed out")
    monkeypatch.setattr(http.urllib.request, "urlopen", slow)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(http.ExternalError) as e:
        http.request_json("https://example.invalid/x", retries=0)
    assert e.value.code == "TIMEOUT"


# ================================================================== packaged front/back
BACK_TEXT = """INGREDIENTS: Wheat flour, sugar, palm oil, emulsifier (INS 322).
NUTRITIONAL INFORMATION Per 100 g
Energy 480 kcal
Protein 7 g
Total Sugars 20 g
Sodium 300 mg"""


def reading(same="yes", front_brand="Sunbake", back_brand="Sunbake", sugars=20.0, ingredients=None):
    return {"status": "ok", "same_product": same,
            "front": {"readable": True, "brand": front_brand, "product_name": "Oat Biscuits", "variant": "Honey", "package_type": "box",
                      "net_quantity": "200 g", "claims": ["high fibre"]},
            "back": {"readable": True, "brand": back_brand, "product_name": "Oat Biscuits", "ingredients_text": ingredients,
                     "serving_size": "30 g", "allergen_statements": ["Contains: wheat"], "additives": ["Emulsifier (INS 322)", "Raising agent"],
                     "manufacturer": "Sunbake Foods Pvt Ltd", "warnings": [],
                     "nutrients": [{"name": "Energy", "amount": 480, "unit": "kcal", "basis": "per 100 g", "key": "energy_kcal", "value": 480.0},
                                   {"name": "Total sugars", "amount": sugars, "unit": "g", "basis": "per 100 g", "key": "total_sugars_g", "value": sugars},
                                   {"name": "Dietary fibre", "amount": 6, "unit": "g", "basis": "per 100 g", "key": "dietary_fibre_g", "value": 6.0}]}}


@pytest.fixture
def pk(monkeypatch, tmp_path):
    from tests.test_packaged import write_fixture
    monkeypatch.setattr(auth_store, "DB_PATH", tmp_path / "users.db")
    d = write_fixture(tmp_path)
    app.dependency_overrides[packaged_route.get_packaged_data] = lambda: d
    monkeypatch.setattr(packaged_route, "run_ocr", lambda img: {"text": BACK_TEXT, "confidence": 85.0, "word_count": 40, "rotation": 0,
                                                                "quality": "good"})
    monkeypatch.setattr(packaged_route, "run_package_reading", lambda f, b: reading())
    yield monkeypatch
    app.dependency_overrides.clear()


def post_pk(c, front=True, back=True, **form):
    files = {}
    if front:
        files["front"] = ("front.png", png("blue"), "image/png")
    if back:
        files["back"] = ("back.png", png("white"), "image/png")
    return c.post("/api/analyze/packaged", files=files, data=form)


def test_front_and_back_are_processed_together(pk):
    j = post_pk(TestClient(app)).json()
    assert j["success"] and j["images"] == {"front": True, "back": True} and j["consistency"]["status"] == "consistent"
    assert j["identity"]["brand"] == "Sunbake" and j["identity"]["variant"] == "Honey" and j["category"] == "Packaged Food"
    rows = {r["key"]: r for r in j["label_nutrition"]["rows"]}
    assert rows["energy_kcal"]["status"] == "agree" and rows["energy_kcal"]["value"] == 480
    assert rows["sodium_mg"]["status"] == "ocr_only" and rows["dietary_fibre_g"]["status"] == "ai_only"
    assert j["label_nutrition"]["basis"] == "per 100 g"
    assert any(a["code"] == "322" and a["found_on_label"] for a in j["additives"])
    assert j["unidentified_additives"] == ["Raising agent"]  # named without a code: reported, not guessed


def test_conflicting_readings_are_not_resolved_by_guessing(pk):
    pk.setattr(packaged_route, "run_package_reading", lambda f, b: reading(sugars=2.0))
    j = post_pk(TestClient(app)).json()
    row = {r["key"]: r for r in j["label_nutrition"]["rows"]}["total_sugars_g"]
    assert row["status"] == "conflict" and row["value"] is None and row["ocr_value"] == 20 and row["ai_value"] == 2
    assert any("read differently" in w for w in j["warnings"])


def test_mismatched_front_and_back_require_confirmation(pk):
    pk.setattr(packaged_route, "run_package_reading", lambda f, b: reading(same="no", back_brand="Crunchy Co"))
    r = post_pk(TestClient(app))
    assert r.status_code == 409 and r.json()["error_code"] == "PACKAGE_MISMATCH" and r.json()["requires_confirmation"]
    assert "label_nutrition" not in r.json()  # nothing combined before the user confirms
    ok = post_pk(TestClient(app), confirm_same_product="true").json()
    assert ok["success"] and any("confirmed" in w for w in ok["warnings"])


def test_front_only_identifies_and_warns_about_missing_label(pk):
    j = post_pk(TestClient(app), back=False).json()
    assert j["success"] and j["images"] == {"front": True, "back": False}
    assert any("Only the front" in w for w in j["warnings"])


def test_unreadable_ocr_uses_openai_reading_of_the_same_image(pk):
    pk.setattr(packaged_route, "run_ocr", lambda img: {"text": "", "confidence": 0.0, "word_count": 0, "rotation": 0, "quality": "unreadable"})
    pk.setattr(packaged_route, "run_package_reading", lambda f, b: reading(ingredients="Wheat flour, sugar, emulsifier (INS 322)"))
    j = post_pk(TestClient(app), front=False).json()
    assert j["success"] and j["label"]["ingredients_source"] == "OpenAI Vision reading of the back label"
    assert {r["status"] for r in j["label_nutrition"]["rows"]} == {"ai_only"}


def test_nothing_readable_is_an_honest_error(pk):
    pk.setattr(packaged_route, "run_ocr", lambda img: {"text": "", "confidence": 0.0, "word_count": 0, "rotation": 0, "quality": "unreadable"})
    pk.setattr(packaged_route, "run_package_reading", lambda f, b: {"status": "unavailable", "reason": "not_configured"})
    r = post_pk(TestClient(app), front=False)
    assert r.status_code == 422 and r.json()["error_code"] == "LABEL_UNREADABLE"
    assert TestClient(app).post("/api/analyze/packaged").json()["error_code"] == "NO_IMAGE"


def test_package_reading_parser_validates_and_converts():
    out = openai_vision.parse_package(SimpleNamespace(output_text=json.dumps({
        "same_product": "maybe",
        "front": {"readable": True, "brand": " Sunbake ", "product_name": None, "variant": None, "package_type": None, "net_quantity": None, "claims": []},
        "back": {"readable": True, "brand": None, "product_name": None, "ingredients_text": "x", "serving_size": None, "allergen_statements": [],
                 "additives": [], "manufacturer": None, "warnings": [],
                 "nutrients": [{"name": "Sodium", "amount": 0.3, "unit": "g", "basis": "Per 100g"},
                               {"name": "Energy", "amount": 2000, "unit": "kJ", "basis": "per 100 g"},
                               {"name": "Protein", "amount": -1, "unit": "g", "basis": "per 100 g"}]}})))
    n = {r["key"]: r for r in out["back"]["nutrients"]}
    assert out["same_product"] == "unclear" and out["front"]["brand"] == "Sunbake"
    assert n["sodium_mg"]["value"] == 300 and n["sodium_mg"]["basis"] == "per 100 g"
    assert round(n["energy_kcal"]["value"], 1) == 478.0 and "protein_g" not in n  # negative amount dropped
    with pytest.raises(openai_vision.OpenAIVisionError):
        openai_vision.parse_package(SimpleNamespace(output_text="not json"))


# ================================================================== history persistence + reports
def test_successful_scan_is_saved_automatically_once_and_survives_restart(env):
    env.rec.food, env.rec.score = "Apple", 0.95
    env.mp.setattr(openai_vision, "identify", lambda img, classes: oa("recognized", "Apple", "Apple", "Fruits"))
    c = cookie_client()
    key = str(uuid.uuid4())
    first = analyse(c, key).json()
    retry = analyse(c, key).json()  # e.g. the browser retried the same request
    assert first["history"]["saved"] and not first["history"]["duplicate"]
    assert retry["history"]["duplicate"] and retry["history"]["scan_id"] == first["history"]["scan_id"]
    analysis_store.clear()  # simulates a server restart: in-memory results are gone, the database is not
    items = c.get("/api/history").json()["items"]
    assert len(items) == 1 and items[0]["summary"]["category"] == "Fruits"
    assert items[0]["summary"]["identity"]["verified_by"] == ["SmartPlateAI image model", "OpenAI Vision"]
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM scans WHERE id = ?", (first["history"]["scan_id"],)).fetchone()[0] == 1
    pdf = c.get(f"/api/reports/scans/{first['history']['scan_id']}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    other = cookie_client()
    assert other.get(f"/api/reports/scans/{first['history']['scan_id']}").status_code == 404
    assert other.get("/api/history").json()["total"] == 0


def test_failed_or_uncertain_analyses_are_not_saved(env):
    c = cookie_client()
    body = analyse(c).json()  # red onion vs tomato -> needs confirmation
    assert body["error_code"] == "LOW_CONFIDENCE" and "history" not in body
    assert c.get("/api/history").json()["total"] == 0
    confirmed = c.post("/api/analyze/confirm", json={"food": "Red Onion", "pending_id": body["pending_id"]}).json()
    assert confirmed["history"]["saved"]
    item = c.get("/api/history").json()["items"][0]
    assert item["title"] == "Red Onion" and item["summary"]["identity"]["source"] == "user_confirmed"


def test_anonymous_scan_is_not_saved_and_says_why(env):
    env.rec.decision = "unsupported_food"
    body = analyse(TestClient(app)).json()
    assert body["history"]["saved"] is False and body["history"]["reason"] == "not_signed_in"


def test_report_for_scan_with_missing_nutrition(env):
    env.rec.decision = "unsupported_food"
    env.mp.setattr(openai_vision, "identify", lambda img, classes: oa(food="Durian", category="Fruits"))
    c = cookie_client()
    sid = analyse(c).json()["history"]["scan_id"]
    pdf = c.get(f"/api/reports/scans/{sid}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    empty = cookie_client().get("/api/reports/nutrition?period=week")
    assert empty.status_code == 200 and empty.content.startswith(b"%PDF")  # empty history still produces a valid report


# ================================================================== chatbot formatting instructions
def test_chat_prompt_requires_markdown_tables_and_no_raw_json():
    payload = chat.build_payload("Explain the nutrition", [], {"kind": "fresh", "title": "Apple", "status": "verified"})
    system = payload["systemInstruction"]["parts"][0]["text"]
    assert "| Nutrient | Amount | Basis |" in system and "Never output raw JSON" in system and '"Apple"' in system
