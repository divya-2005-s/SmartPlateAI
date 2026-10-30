"""Packaged labels: Gemini reads the label when OpenAI gives no answer (same prompt, schema and validation), every value says
which reader produced it, and the OCR parser never assigns a column basis it cannot see.

OpenAI and Gemini are MOCKED (Gemini replies imitate the generateContent JSON shape); no network or paid calls. Two parser
tests use OCR text as Tesseract actually read it from real labels in data_eval/packaged (Parle-G and Maaza, Open Food Facts)."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes import packaged as packaged_route
from app.main import app
from app.services import gemini_vision, openai_vision
from app.services.label_parser import extract_nutrition
from tests.test_recognition_packaged_history_fixes import pk, post_pk  # noqa: F401  (fixture)

QUOTA = openai_vision.OpenAIVisionError("quota_exhausted")
REAL_READING = packaged_route.run_package_reading  # captured before any fixture replaces it


def package_body(sugars=20.0) -> dict:
    payload = {"same_product": "yes",
               "front": {"readable": True, "brand": "Sunbake", "product_name": "Oat Biscuits", "variant": "Honey", "package_type": "box",
                         "net_quantity": "200 g", "claims": []},
               "back": {"readable": True, "brand": "Sunbake", "product_name": "Oat Biscuits", "ingredients_text": "Oats, sugar, salt",
                        "serving_size": "30 g", "allergen_statements": ["Contains: oats"], "additives": [], "manufacturer": None,
                        "warnings": [],
                        "nutrients": [{"name": "Energy", "amount": 480, "unit": "kcal", "basis": "per 100 g"},
                                      {"name": "Total sugars", "amount": sugars, "unit": "g", "basis": "per 100 g"},
                                      {"name": "Dietary fibre", "amount": 6, "unit": "g", "basis": "per 100 g"}]}}
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}


@pytest.fixture
def providers(monkeypatch):
    """OpenAI 'ready' but out of credit; Gemini enabled with a fake key. `state` controls both; `calls` records Gemini calls."""
    state = SimpleNamespace(openai=QUOTA, gemini=package_body(), calls=[])

    def openai_read(front, back):
        if isinstance(state.openai, Exception):
            raise state.openai
        return state.openai
    monkeypatch.setattr(openai_vision, "availability", lambda: "ready")
    monkeypatch.setattr(openai_vision, "read_package", openai_read)
    monkeypatch.setattr(gemini_vision, "get_settings", lambda: SimpleNamespace(
        gemini_vision_enabled=True, gemini_vision_model="model-a", gemini_vision_timeout_s=5))
    monkeypatch.setattr(gemini_vision.chat, "api_key", lambda: "test-key")

    def post(url, payload, key, timeout):
        state.calls.append(payload)
        if isinstance(state.gemini, Exception):
            raise state.gemini
        return state.gemini
    monkeypatch.setattr(gemini_vision, "post", post)
    return state


def test_gemini_reads_the_label_when_openai_has_no_credit(providers):
    from PIL import Image
    r = packaged_route.run_package_reading(Image.new("RGB", (40, 40)), Image.new("RGB", (40, 40)))
    assert r["status"] == "ok" and r["provider"] == "Google Gemini" and r["fallback_from"] == {"provider": "OpenAI Vision", "reason": "quota_exhausted"}
    assert {n["key"] for n in r["back"]["nutrients"]} >= {"energy_kcal", "total_sugars_g"}
    parts = providers.calls[0]["contents"][0]["parts"]
    assert "FRONT" in parts[0]["text"] and "BACK" in parts[0]["text"] and len(parts) == 3  # prompt + two images, one request


def test_openai_answer_never_calls_gemini(providers):
    from PIL import Image
    providers.openai = {"same_product": "yes", "front": {"readable": False}, "back": {"readable": False}}
    r = packaged_route.run_package_reading(Image.new("RGB", (40, 40)), None)
    assert r["provider"] == "OpenAI Vision" and providers.calls == []


@pytest.mark.parametrize("gemini", [openai_vision.OpenAIVisionError("timeout"),
                                    {"candidates": [{"content": {"parts": [{"text": "{\"not\": \"a package\"}"}]}}]}],
                         ids=["gemini_timeout", "gemini_invalid_reply"])
def test_both_readers_failing_is_reported_and_nothing_is_invented(providers, gemini):
    from PIL import Image
    providers.gemini = gemini
    r = packaged_route.run_package_reading(Image.new("RGB", (40, 40)), Image.new("RGB", (40, 40)))
    assert r["status"] == "unavailable" and r["reason"] == "quota_exhausted"
    assert r["fallback"]["provider"] == "Google Gemini" and r["fallback"]["reason"] in ("timeout", "invalid_response")


def test_route_names_gemini_as_the_source_of_what_it_read(pk, providers):  # noqa: F811
    pk.setattr(packaged_route, "run_package_reading", REAL_READING)
    j = post_pk(TestClient(app)).json()
    rows = {r["key"]: r for r in j["label_nutrition"]["rows"]}
    assert rows["energy_kcal"]["source"] == "package label (Tesseract OCR and Google Gemini agree)"
    assert rows["dietary_fibre_g"]["source"] == "package label (Google Gemini reading)"
    assert j["identity"]["source"] == "Google Gemini reading of the package (as printed)"
    assert j["package_reading"]["provider"] == "Google Gemini"


def test_route_reports_both_failures(pk, providers):  # noqa: F811
    providers.gemini = openai_vision.OpenAIVisionError("timeout")
    pk.setattr(packaged_route, "run_package_reading", REAL_READING)
    j = post_pk(TestClient(app)).json()
    assert any("Google Gemini fallback also failed (timeout)" in w for w in j["warnings"])
    assert all(r["source"] == "package label (Tesseract OCR)" for r in j["label_nutrition"]["rows"])


# ------------------------------------------------------------------ OCR parser: the column basis is never guessed
PARLE_G_OCR = """NUTRITIONAL INFORMATION~
SERVE SIZE: 15 g PER SERVE
ENERGY (kcal)
TOTALSUGARS(g) 25.5
ADDED SUGARS (g) 25.0
TOTAL FAT (g) 13.0
SODIUM (mg) 296"""

MAAZA_OCR = """Nutrition information
(approximate values)
SERVING = 200 ml: 2.4
SERVINGS IN THIS PACK
Amount per serving
Calories O
___PER100ml_ tox" Pensenve
Energy 63 kcal 6.3%
Carbohydrate 15.89
Totalsugars 14.99
Total fat 0g 0%"""


def test_values_larger_than_the_serving_cannot_be_per_serving():
    n = extract_nutrition(PARLE_G_OCR)  # real OCR: the "AMOUNT PER 100g" heading was lost, only "PER SERVE" survived
    assert n["basis"] == "unknown" and "exceed the 15 g serving size" in n["basis_note"]
    assert n["values"]["total_fat_g"]["value"] == 13.0  # the value is kept; only its basis is withheld


def test_headings_on_different_lines_do_not_decide_the_column():
    n = extract_nutrition(MAAZA_OCR)  # "Amount per serving" title and a "PER100ml" column: order unknown
    assert n["basis"] == "unknown" and n["values"]["energy_kcal"]["value"] == 63.0


def test_unit_g_read_as_9_is_not_shown_as_a_number():
    n = extract_nutrition(MAAZA_OCR)
    assert "carbohydrate_g" not in n["values"] and n["unreadable"][0]["key"] == "carbohydrate_g"


@pytest.mark.parametrize("header,basis", [("Nutrition Facts Per 100 g Per serving (30 g)", "per 100 g"),
                                          ("Nutrition Facts Per serving (30 g) Per 100 g", "per serving"),
                                          ("Nutritional information per 100 g", "per 100 g"),
                                          ("Amount per serving", "per serving")])
def test_basis_from_a_single_header_line(header, basis):
    assert extract_nutrition(header + "\nEnergy 120 kcal\nProtein 3 g")["basis"] == basis


def test_route_surfaces_basis_and_unreadable_warnings(pk):  # noqa: F811
    pk.setattr(packaged_route, "run_ocr", lambda img: {"text": MAAZA_OCR, "confidence": 80.0, "word_count": 30, "rotation": 0, "quality": "good"})
    pk.setattr(packaged_route, "run_package_reading", lambda f, b: {"status": "unavailable", "reason": "not_configured"})
    j = post_pk(TestClient(app)).json()
    assert any("could not be read reliably" in w and "Carbohydrate" in w for w in j["warnings"])
    assert j["label_nutrition"]["basis"] == "unknown"
