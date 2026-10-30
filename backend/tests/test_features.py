"""BMI, comparison, allergens, Vision fusion, Open Food Facts, PubChem/chemistry, freshness, PDF reports, meal planner and chat
streaming. All external services are mocked; no network is used."""
import io
import json
import urllib.error
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.routes import analyze, packaged as packaged_route
from app.core.config import Settings
from app.main import app
from app.ml import freshness as F
from app.services import allergens as A
from app.services import analysis_store, chat, chemistry, http, openfoodfacts as off, vision
from app.services import meal_planner as MP
from app.services.bmi import BMIError, calculate, to_metric
from app.services.pdf import PDF

client = TestClient(app)


def auth_user():
    r = client.post("/api/auth/signup", json={"name": "Test User", "email": f"t_{uuid.uuid4().hex[:8]}@example.com", "password": "password-123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ------------------------------------------------------------------ BMI
def test_bmi_adult_child_units_and_validation():
    r = calculate(170, 65, 30)
    assert r["bmi"] == 22.5 and r["category"] == "Healthy weight" and r["indian_category"] == "Normal"
    assert calculate(170, 70, 30)["indian_category"] == "Overweight" and calculate(170, 70, 30)["category"] == "Healthy weight"
    child = calculate(150, 45, 12)
    assert child["category"] is None and not child["adult_categories_apply"] and "percentile" in child["interpretation"]
    h, w = to_metric(height_ft=5, height_in=7, weight_lb=150)
    assert h == pytest.approx(170.18) and w == pytest.approx(68.04, abs=0.01)
    with pytest.raises(BMIError):
        to_metric(height_cm=20, weight_kg=60)
    j = client.post("/api/tools/bmi", json={"height_cm": 180, "weight_kg": 90}).json()
    assert j["category"] == "Overweight" and "age_note" in j
    assert client.post("/api/tools/bmi", json={"height_cm": 180}).json()["error_code"] == "INVALID_INPUT"


# ------------------------------------------------------------------ allergens
def test_allergen_detection_synonyms_and_incomplete_labels():
    det = A.detect("Wheat flour (maida), sugar, ghee, soy lecithin", "Contains: wheat. May contain traces of peanuts and sesame.")
    by = {a["key"]: a for a in det["allergens"]}
    assert by["wheat_gluten"]["status"] == "contains" and by["milk"]["status"] == "contains" and by["soy"]["status"] == "contains"
    assert by["peanut"]["status"] == "may_contain" and by["sesame"]["status"] == "may_contain"
    m = A.match_prefs(det, [{"allergen": "milk", "severity": "severe"}, {"allergen": "peanut"}, {"allergen": "fish"}])
    assert [x["allergen"] for x in m["confirmed"]] == ["milk"] and [x["allergen"] for x in m["possible"]] == ["peanut"]
    empty = A.match_prefs(A.detect(None, "Net wt 50 g"), [{"allergen": "milk"}])
    assert not empty["confirmed"] and any("Incomplete label" in w for w in empty["warnings"])
    assert A.ingredients_conflicts(["Paneer tikka", "Rice"], [{"allergen": "milk"}])[0]["ingredients"] == ["Paneer tikka"]


# ------------------------------------------------------------------ Vision fusion
CLASSES = ["Apple", "Banana", "Taco", "French Fries"]


def test_vision_assess_agree_conflict_generic_nofood():
    agree = vision.assess({"labels": [{"name": "Food", "score": 0.98}, {"name": "Apple", "score": 0.95}]}, "Apple", CLASSES, 0.7)
    assert agree["status"] == "agrees"
    conflict = vision.assess({"labels": [{"name": "Burrito", "score": 0.91}]}, "Taco", CLASSES, 0.7)
    assert conflict["status"] == "conflicts" and conflict["hints_outside_supported"] == ["Burrito"]
    other = vision.assess({"labels": [{"name": "Banana", "score": 0.9}]}, "Apple", CLASSES, 0.7)
    assert other["status"] == "conflicts" and other["conflicting_supported_foods"] == ["Banana"]
    generic = vision.assess({"labels": [{"name": "Food", "score": 0.97}, {"name": "Ingredient", "score": 0.9}]}, "Apple", CLASSES, 0.7)
    assert generic["status"] == "generic"
    nofood = vision.assess({"labels": [{"name": "Laptop", "score": 0.95}, {"name": "Tableware", "score": 0.8}]}, "Apple", CLASSES, 0.7)
    assert nofood["status"] == "no_food"
    weak = vision.assess({"labels": [{"name": "Burrito", "score": 0.4}, {"name": "Food", "score": 0.9}]}, "Taco", CLASSES, 0.7)
    assert weak["status"] == "generic"  # low-score labels are ignored


class Rec:
    status_message = "ready"
    class_names = CLASSES

    def load(self):
        return True

    def analyze_image(self, img):
        top = [{"class_id": 2, "food": "Taco", "score": 0.9}, {"class_id": 0, "food": "Apple", "score": 0.05}]
        return {"decision": "accept", "reason": None, "calibrated": True, "confidence": 0.9, "margin": 0.85, "top_k": top, "signals": {},
                "freshness": {"status": "not_assessed", "confidence": None, "message": "x"}}


class Nut:
    error = None

    def lookup(self, food, serving=None):
        return {"basis": "per 100 g", "nutrients": [], "not_available": [], "source_fdc_id": None}


def png():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (64, 64), "orange").save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def fake_model():
    app.dependency_overrides[analyze.get_recognizer] = lambda: Rec()
    app.dependency_overrides[analyze.get_nutrition] = lambda: Nut()
    yield
    app.dependency_overrides.clear()


def test_api_vision_conflict_downgrades_to_confirmation(fake_model, monkeypatch):
    monkeypatch.setattr(vision, "enabled", lambda: True)
    monkeypatch.setattr(vision, "annotate", lambda img: {"labels": [{"name": "Burrito", "score": 0.93}], "objects": []})
    j = client.post("/api/analyze/food", files={"file": ("a.png", png(), "image/png")}).json()
    assert j["error_code"] == "LOW_CONFIDENCE" and j["reason"] == "vision_disagreement" and j["candidates"]
    assert j["vision"]["hints_outside_supported"] == ["Burrito"]


def test_api_vision_agreement_and_outage_keep_prediction(fake_model, monkeypatch):
    monkeypatch.setattr(vision, "enabled", lambda: True)
    monkeypatch.setattr(vision, "annotate", lambda img: {"labels": [{"name": "Taco", "score": 0.9}], "objects": []})
    j = client.post("/api/analyze/food", files={"file": ("a.png", png(), "image/png")}).json()
    assert j["success"] and j["vision"]["status"] == "agrees" and j["analysis_id"] and j["precautions"]

    def down(img):
        raise vision.VisionUnavailable("RATE_LIMITED: quota")
    monkeypatch.setattr(vision, "annotate", down)
    j = client.post("/api/analyze/food", files={"file": ("a.png", png(), "image/png")}).json()
    assert j["success"] and j["vision"]["status"] == "unavailable"


def test_vision_billing_error_is_clear_and_blocks_retries(fake_model, monkeypatch):
    from PIL import Image

    calls = {"count": 0}

    def fake_request_json(url, **kwargs):
        calls["count"] += 1
        raise http.ExternalError("BILLING_REQUIRED", "Google Cloud billing is not enabled for project XYZ.", 403)

    monkeypatch.setattr(vision, "get_settings", lambda: Settings(google_vision_api_key="test-key", vision_enabled=True))
    monkeypatch.setattr(vision, "request_json", fake_request_json)
    monkeypatch.setattr(vision, "cache_get", lambda key: None)
    monkeypatch.setattr(vision, "cache_set", lambda key, value, ttl: None)

    with pytest.raises(vision.VisionUnavailable, match="billing.*Google Cloud"):
        vision.annotate(Image.new("RGB", (16, 16), color="red"))

    assert calls["count"] == 1
    assert vision.enabled() is False


def test_vision_not_configured_means_no_call(fake_model, monkeypatch):
    def boom(img):
        raise AssertionError("must not be called")
    monkeypatch.setattr(vision, "annotate", boom)
    j = client.post("/api/analyze/food", files={"file": ("a.png", png(), "image/png")}).json()
    assert j["success"] and j["vision"] is None


# ------------------------------------------------------------------ Open Food Facts
OFF_PRODUCT = {"status": 1, "product": {"code": "8901234567890", "product_name": "Masala Potato Chips", "brands": "Cruncho",
                                        "ingredients_text": "Potato, oil, milk solids", "allergens_tags": ["en:milk"], "traces_tags": ["en:peanuts"],
                                        "additives_tags": ["en:e627", "en:e500ii"],
                                        "nutriments": {"energy-kcal_100g": 540, "proteins_100g": 6.5, "sodium_100g": 0.78, "fat_100g": 34}}}


def test_off_barcode_validation_parse_cache_and_conflicts(monkeypatch):
    monkeypatch.setattr(off, "enabled", lambda: True)
    store = {}
    monkeypatch.setattr(off, "cache_get", lambda k: store.get(k))
    monkeypatch.setattr(off, "cache_set", lambda k, v, ttl: store.__setitem__(k, v))
    calls = []

    def fake(url, **kw):
        calls.append(url)
        return OFF_PRODUCT
    monkeypatch.setattr(off, "request_json", fake)
    assert off.valid_barcode("8901234567890") and not off.valid_barcode("8901234567891") and not off.valid_barcode("12345")
    assert off.by_barcode("8901234567891")["status"] == "invalid" and not calls
    r = off.by_barcode("8901234567890")
    p = r["product"]
    assert r["status"] == "found" and p["nutrition_per_100g"]["sodium_mg"] == 780.0 and p["additive_codes"] == ["627", "500(ii)"]
    assert p["allergens"] == ["milk"] and p["traces"] == ["peanut"]
    off.by_barcode("8901234567890")
    assert len(calls) == 1  # second call served from cache
    c = off.conflicts({"energy_kcal": 400, "sodium_mg": 790}, "per 100 g", p["nutrition_per_100g"])
    assert [x["nutrient"] for x in c] == ["energy_kcal"]
    assert off.conflicts({"energy_kcal": 400}, "per serving", p["nutrition_per_100g"]) == []


def test_off_name_search_requires_brand_and_name(monkeypatch):
    monkeypatch.setattr(off, "enabled", lambda: True)
    monkeypatch.setattr(off, "cache_get", lambda k: None)
    monkeypatch.setattr(off, "cache_set", lambda *a: None)
    monkeypatch.setattr(off, "request_json", lambda url, **kw: {"products": [OFF_PRODUCT["product"]]})
    assert off.search("Masala Potato Chips", "Cruncho")["status"] == "found"
    assert off.search("Masala Potato Chips", "OtherBrand")["status"] == "unconfirmed"


def test_off_outage_is_reported(monkeypatch):
    monkeypatch.setattr(off, "enabled", lambda: True)
    monkeypatch.setattr(off, "cache_get", lambda k: None)

    def down(url, **kw):
        raise http.ExternalError("UNREACHABLE", "x")
    monkeypatch.setattr(off, "request_json", down)
    assert off.by_barcode("8901234567890")["status"] == "unavailable"


# ------------------------------------------------------------------ chemistry
def test_chemical_profile_amounts_only_from_usda(monkeypatch):
    monkeypatch.setattr(chemistry, "pubchem", lambda name: {"status": "found", "cid": 446925, "iupac_name": "iupac-" + name, "formula": "C40H56",
                                                          "molecular_weight": 536.9, "url": "https://pubchem.ncbi.nlm.nih.gov/compound/446925"})
    nut = {"source_fdc_id": 123, "nutrients": [{"key": "lycopene_ug", "label": "Lycopene", "unit": "µg", "per_100g": 2573.0},
                                                {"key": "vitamin_c_mg", "label": "Vitamin c", "unit": "mg", "per_100g": None}]}
    r = chemistry.chemical_profile("Tomato", nut)
    by = {c["common_name"]: c for c in r["compounds"]}
    assert by["Lycopene"]["amount"]["value"] == 2573.0 and "USDA" in by["Lycopene"]["amount"]["source"]
    assert by["Vitamin C (ascorbic acid)"]["amount"] is None  # missing in USDA record -> no amount
    assert by["Citric acid"]["amount"] is None and by["Citric acid"]["formula"] == "C40H56"
    assert any("not a laboratory measurement" in x for x in r["limitations"])
    none = chemistry.chemical_profile("Idli", None)
    assert none["status"] == "no_curated_compounds" and none["compounds"] == []


def test_pubchem_disabled_and_outage(monkeypatch):
    assert chemistry.pubchem("lycopene")["status"] == "disabled"  # disabled in tests via conftest
    monkeypatch.setattr(chemistry, "get_settings", lambda: type("S", (), {"pubchem_enabled": True, "http_timeout_s": 1})())
    monkeypatch.setattr(chemistry, "cache_get", lambda k: None)

    def down(url, **kw):
        raise http.ExternalError("UNREACHABLE", "x")
    monkeypatch.setattr(chemistry, "request_json", down)
    assert chemistry.pubchem("lycopene")["status"] == "unavailable"


# ------------------------------------------------------------------ freshness head
def test_freshness_training_thresholds_and_decisions():
    rng = np.random.default_rng(0)
    x = np.vstack([rng.normal(0, 1, (300, 8)), rng.normal(2.5, 1, (300, 8))])
    y = np.array([0] * 300 + [1] * 300)
    head = F.fit_logistic(x, y)
    p = F.predict_proba(head, x)
    assert ((p >= 0.5) == y.astype(bool)).mean() > 0.95
    th = F.choose_thresholds(p, y, 0.95)
    assert th["t_fresh"] < th["t_spoiled"] and th["precision_spoiled"] >= 0.95 and th["precision_fresh"] >= 0.95
    assert F.decide(0.99, th["t_fresh"], th["t_spoiled"]) == "possibly_spoiled" and F.decide(0.01, th["t_fresh"], th["t_spoiled"]) == "fresh"


def test_freshness_head_scope(tmp_path):
    rng = np.random.default_rng(1)
    head = F.fit_logistic(rng.normal(0, 1, (50, 4)), np.array([0, 1] * 25))
    np.savez(tmp_path / "freshness_head.npz", **head)
    (tmp_path / "freshness_config.json").write_text(json.dumps({"food_model_sha256": "abc", "supported_foods": ["Apple"], "t_fresh": 0.3, "t_spoiled": 0.7}))
    h = F.FreshnessHead(tmp_path)
    assert not h.load("different-model") and h.status == "model_mismatch"
    assert h.load("abc")
    assert h.assess(np.zeros(4), "Taco", True)["status"] == "not_assessed"  # not trained for this food
    assert h.assess(np.zeros(4), None, False)["status"] == "not_assessed"  # food not accepted
    assert h.assess(np.zeros(4), "Apple", True)["status"] in ("fresh", "possibly_spoiled", "uncertain")
    assert F.FreshnessHead(tmp_path / "missing").assess(np.zeros(4), "Apple", True)["model_status"] == "not_installed"


# ------------------------------------------------------------------ PDF + reports
def test_pdf_writer_produces_valid_multi_page_pdf():
    pdf = PDF("Test report", "subtitle")
    for i in range(80):
        pdf.text(f"Line {i} with µg and 5 °C and ≥ symbols and a very long word " + "x" * 120)
    pdf.table(["A", "B"], [["1", "2"]] * 5)
    pdf.link("PubChem", "https://pubchem.ncbi.nlm.nih.gov/compound/1")
    data = pdf.build()
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF") and b"/Count " in data
    assert int(data.split(b"/Count ")[1].split(b" ")[0].split(b">")[0]) >= 3
    assert b"/URI" in data


def test_scan_and_nutrition_reports_are_owner_only(fake_model):
    from tests.test_accounts import fresh_result
    a, b = auth_user(), auth_user()
    sid = client.post("/api/history", headers=a, json={"analysis_id": analysis_store.put("fresh", fresh_result("Tomato"))}).json()["scan"]["id"]
    r = client.get(f"/api/reports/scans/{sid}", headers=a)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert client.get(f"/api/reports/scans/{sid}", headers=b).status_code == 404
    assert client.get(f"/api/reports/scans/{sid}").status_code == 401
    client.post("/api/nutrition/entries", headers=a, json={"logged_on": "2026-10-12", "name": "Dal", "nutrients": {"energy_kcal": 250}})
    w = client.get("/api/reports/nutrition?period=week&day=2026-10-12", headers=a)
    assert w.status_code == 200 and w.content.startswith(b"%PDF")


# ------------------------------------------------------------------ meal planner (Gemini mocked)
PLAN_JSON = json.dumps({"days": [{"day": 1, "meals": [
    {"meal": "breakfast", "name": "Poha with peanuts", "ingredients": [{"item": "Poha", "grams": 60}, {"item": "Peanuts", "grams": 15}],
     "estimated_nutrition": {"energy_kcal": 320, "protein_g": 9}},
    {"meal": "lunch", "name": "Dal and rice", "ingredients": [{"item": "Toor dal", "grams": 50}, {"item": "Rice", "grams": 80}],
     "estimated_nutrition": {"energy_kcal": 450}}]}]})


def test_meal_plan_flow_with_allergen_recheck(monkeypatch):
    a = auth_user()
    client.put("/api/allergens/preferences", headers=a, json={"allergens": [{"allergen": "peanut", "severity": "severe"}]})
    assert client.post("/api/meal-plans", headers=a, json={"days": 1}).json()["error_code"] == "CHAT_NOT_CONFIGURED"
    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "post_json", lambda url, payload, key: {"candidates": [{"content": {"parts": [{"text": PLAN_JSON}]}}]})
    r = client.post("/api/meal-plans", headers=a, json={"days": 1, "disliked_foods": ["rice"]})
    assert r.status_code == 201, r.text
    plan = r.json()["plan"]
    meals = {m["meal"]: m for m in plan["plan"]["days"][0]["meals"]}
    assert meals["breakfast"]["allergen_conflicts"][0]["allergen"] == "peanut" and meals["breakfast"]["needs_attention"]
    assert meals["lunch"]["disliked_found"] == ["rice"]
    # The breakfast names the user's declared allergen, so it is withheld: not counted in the day's totals and its
    # ingredients are not put on the shopping list (previously 770 kcal with peanuts listed).
    assert meals["breakfast"]["withheld"] and not meals["lunch"]["withheld"]
    assert plan["plan"]["days"][0]["totals_estimate"]["energy_kcal"]["total"] == 450
    assert not any(i["item"] == "peanuts" for i in plan["plan"]["shopping_list"])
    assert any(i["item"] == "toor dal" for i in plan["plan"]["shopping_list"])
    pid = plan["id"]
    edited = client.put(f"/api/meal-plans/{pid}/meal", headers=a, json={"day": 1, "meal": "breakfast", "name": "Upma",
                                                                        "ingredients": [{"item": "Semolina", "grams": 60}]}).json()
    bf = [m for m in edited["plan"]["plan"]["days"][0]["meals"] if m["meal"] == "breakfast"][0]
    assert bf["name"] == "Upma" and not bf["allergen_conflicts"] and bf["edited_by_user"]
    b = auth_user()
    assert client.get(f"/api/meal-plans/{pid}", headers=b).status_code == 404
    assert client.delete(f"/api/meal-plans/{pid}", headers=a).json()["success"]


def test_plan_parser_rejects_garbage():
    with pytest.raises(ValueError):
        MP.parse_plan('{"days": []}', 1)
    assert MP.parse_plan("```json\n" + PLAN_JSON + "\n```", 1)["days"][0]["meals"][0]["name"] == "Poha with peanuts"


# ------------------------------------------------------------------ chat streaming, retries, cache
class FakeStream:
    def __init__(self, chunks):
        self.lines = [("data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": c}]}}]}) + "\n").encode() for c in chunks]

    def __iter__(self):
        return iter(self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_chat_stream_sse(monkeypatch):
    chat.clear_cache()
    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "open_stream", lambda url, payload, key: FakeStream(["Apple has ", "52 kcal."]))
    r = client.post("/api/chat/stream", json={"message": "calories?", "context": {"kind": "fresh", "title": "Apple", "status": "x"}})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert '"Apple has "' in r.text and "event: done" in r.text and "latency_ms" in r.text


def test_chat_stream_errors_before_first_chunk(monkeypatch):
    monkeypatch.setattr(chat, "api_key", lambda: "")
    assert client.post("/api/chat/stream", json={"message": "hi"}).json()["error_code"] == "CHAT_NOT_CONFIGURED"


def test_chat_retry_then_success_and_cache(monkeypatch):
    chat.clear_cache()
    calls = []

    def flaky(url, payload, key):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(url, 503, "busy", {}, io.BytesIO(b"{}"))
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "post_json", flaky)
    j = client.post("/api/chat", json={"message": "retry please"}).json()
    assert j["reply"] == "ok" and len(calls) == 2 and j["cached"] is False and "latency_ms" in j
    j2 = client.post("/api/chat", json={"message": "retry please"}).json()
    assert j2["cached"] is True and len(calls) == 2


def test_compact_context_drops_empty_values():
    block = chat.context_block({"a": None, "b": [], "c": {"d": None, "e": 1.23456}, "f": "x"})
    assert '"a"' not in block and '"b"' not in block and '"e":1.235' in block


# ------------------------------------------------------------------ packaged: personal alerts + comparison
def test_packaged_personal_alerts_and_compare(tmp_path, monkeypatch):
    from tests.test_packaged import LABEL, write_fixture
    d = write_fixture(tmp_path)
    app.dependency_overrides[packaged_route.get_packaged_data] = lambda: d
    try:
        a = auth_user()
        client.put("/api/allergens/preferences", headers=a, json={"allergens": [{"allergen": "milk"}, {"allergen": "peanut"}]})
        monkeypatch.setattr(packaged_route, "run_ocr", lambda img: {"text": LABEL, "confidence": 88.0, "word_count": 80, "rotation": 0, "quality": "good"})
        j = client.post("/api/analyze/packaged", headers=a, files={"file": ("l.png", png(), "image/png")}).json()
        al = j["allergen_alerts"]
        assert [x["allergen"] for x in al["confirmed"]] == ["milk"] and [x["allergen"] for x in al["possible"]] == ["peanut"]
        assert j["analysis_id"] and j["external"] is None  # OFF disabled in tests
        anon = client.post("/api/analyze/packaged", files={"file": ("l.png", png(), "image/png")}).json()
        assert anon["allergen_alerts"] is None
        d.load()
        ids = ",".join(p["id"] for p in d.products[:3])
        c = client.get(f"/api/packaged/compare?ids={ids}&priorities=lower_sodium,higher_protein", headers=a).json()
        assert c["success"] and len(c["products"]) == 3
        biscuits = [p for p in c["products"] if p["name"] == "Glucose Biscuits"][0]
        assert not biscuits["comparable"] and all(v is None for v in biscuits["values"].values())  # basis unknown -> not compared
        assert "Salted Potato Chips" in c["findings"][0]["text"] and "could not be compared" in c["findings"][0]["text"]
        assert client.get("/api/packaged/compare?ids=1").json()["error_code"] == "INVALID_SELECTION"
        assert client.get(f"/api/packaged/compare?ids={ids}&priorities=healthiest").json()["error_code"] == "INVALID_PRIORITY"
    finally:
        app.dependency_overrides.clear()
