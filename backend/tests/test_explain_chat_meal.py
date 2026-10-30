"""Ingredients explained, chatbot grounding/fallback and meal-planner verified nutrition. Every external service is mocked:
no Gemini, USDA, PubChem or Open Food Facts call is made."""
import json
import re
import urllib.error
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.routes import analyze
from app.data.ingredient_glossary import ENTRIES, TOPICS
from app.main import app
from app.services import chat, ingredients_explain as X, meal_nutrition, usda

client = TestClient(app)
SECRET = "sk-test-NEVER-RETURN-THIS-KEY-1234567890"


def auth_user():
    r = client.post("/api/auth/signup", json={"name": "Test User", "email": f"t_{uuid.uuid4().hex[:8]}@example.com", "password": "password-123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(autouse=True)
def _fresh_chat_cache():
    chat.clear_cache()
    yield
    chat.clear_cache()


# ================================================================== ingredients explained
def test_verified_ingredients_are_explained_with_their_source():
    r = X.explain("Ingredients: Sugar, Acidity Regulator (330), Emulsifier (Soy Lecithin), Preservative (Sodium Benzoate), Ascorbic Acid")
    by = {i["as_written"]: i for i in r["items"]}
    citric = by["Acidity Regulator (330)"]
    assert citric["status"] == "explained" and citric["class"]["name"] == "Acidity regulator"
    c = citric["components"][0]
    assert c["name"] == "Citric acid" and c["ins"] == "330" and "citrus" in c["what"]
    assert c["sources"] and "CAC/GL 36-1989" in c["sources"][0]
    assert by["Emulsifier (Soy Lecithin)"]["components"][0]["name"] == "Lecithins"
    assert "soy" in by["Emulsifier (Soy Lecithin)"]["components"][0]["consider"].lower()
    assert by["Preservative (Sodium Benzoate)"]["components"][0]["ins"] == "211"
    assert "vitamin C" in by["Ascorbic Acid"]["components"][0]["what"]
    assert r["counts"]["explained"] == 5


def test_codes_in_nested_brackets_and_longest_name_wins():
    assert X.codes_in("Raising Agents (503(ii), 500(ii))") == ["503(ii)", "500(ii)"]
    assert X.codes_in("Emulsifier (322 (soy))") == ["322"]
    assert X.codes_in("Wheat flour (60%)") == []  # an amount, not a code
    assert X.alias_matches("Invert Sugar Syrup") == ["invert_sugar"]  # not also "sugar"
    # Some product records separate ingredients with full stops; decimals and bracketed text are not split.
    assert X.split_items("Thickeners (508 & 412). Spices (26.2%) (Onion powder, Cumin). Salt 1.5 g") == [
        "Thickeners (508 & 412)", "Spices (26.2%) (Onion powder, Cumin)", "Salt 1.5 g"]


def test_unknown_additives_are_reported_as_unknown_not_invented():
    r = X.explain("Mystery Compound XYZ, Thickener (1422)")
    mystery, thick = r["items"]
    assert mystery["status"] == "not_found" and mystery["components"] == []
    assert "No verified information" in mystery["message"]
    assert thick["status"] == "partly_explained" and thick["unknown_codes"] == ["INS 1422"]
    assert thick["class"]["name"] == "Thickener"  # the printed class is explained; the code itself is not guessed
    # With the project's additive dataset, the code is named from that dataset only (no invented "what it is").
    r2 = X.explain("Thickener (1422)", additive_lookup=lambda code: {"name": "Acetylated Distarch Adipate", "function": "Thickener",
                                                                      "source": "additive reference CSV"} if code == "1422" else None)
    comp = r2["items"][0]["components"][0]
    assert comp["verification"] == "additive_dataset" and comp["what"] is None and comp["name"] == "Acetylated Distarch Adipate"


def test_label_ocr_uncertainty_is_preserved():
    r = X.explain("Salt, Sugar", source="Tesseract OCR of the back label", uncertain=True)
    assert r["uncertain"] is True and r["source"] == "Tesseract OCR of the back label"
    assert "may contain reading errors" in r["notes"][0]
    assert [i["as_written"] for i in r["items"]] == ["Salt", "Sugar"]  # text kept as written


def test_no_intake_limits_concentrations_or_toxicity_values_in_reference_text():
    text = json.dumps({"entries": ENTRIES, "topics": TOPICS})
    for banned in (r"\bADI\b", r"acceptable daily intake", r"mg/kg\s*(bw|body)", r"\bppm\b", r"\bLD50\b", r"\btoxic dose\b"):
        assert not re.search(banned, text, re.I), banned
    # The dataset's JECFA "ADI" text is never copied into the explanation.
    out = json.dumps(X.explain("Colour (102)", additive_lookup=lambda c: {"name": "Tartrazine", "function": "Color",
                                                                          "notes": "Evaluated - ADI 0-10 mg/kg bw"}))
    assert "ADI" not in out and "mg/kg" not in out


def test_explain_endpoint_and_validation():
    r = client.post("/api/ingredients/explain", json={"text": "Citric acid, Salt", "source": "product record", "uncertain": False})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["success"] and j["counts"]["total"] == 2 and j["source"] == "product record"
    assert client.post("/api/ingredients/explain", json={"text": ""}).status_code == 422
    assert client.post("/api/ingredients/explain", json={"text": "x" * 5001}).status_code == 422


# ================================================================== chatbot
def _capture(monkeypatch, reply="Direct answer."):
    seen = {}

    def fake(url, payload, key):
        seen["payload"] = payload
        return {"candidates": [{"content": {"parts": [{"text": reply}]}}]}
    monkeypatch.setattr(chat, "api_key", lambda: SECRET)
    monkeypatch.setattr(chat, "post_json", fake)
    return seen


def test_apple_wax_question_is_grounded_and_never_asserted_for_the_users_apple(monkeypatch):
    seen = _capture(monkeypatch)
    r = client.post("/api/chat", json={"message": "Does an apple contain wax?"})
    assert r.status_code == 200 and r.json()["reply"] == "Direct answer."
    system = seen["payload"]["systemInstruction"]["parts"][0]["text"]
    assert "REFERENCE DATA" in system and "Wax on fruit" in system
    assert "naturally produce a thin waxy layer" in system
    assert "shiny appearance alone cannot show" in system.lower()
    assert "should not be assumed to remove every coating" in system
    assert "never assert it for the user's item" in system  # rule 12
    assert "CURRENT ANALYSIS: none" in system


def test_general_food_science_question_needs_no_analysis(monkeypatch):
    seen = _capture(monkeypatch)
    r = client.post("/api/chat", json={"message": "What is the difference between total sugar and added sugar?"})
    assert r.json()["success"] and r.json()["grounded_in_analysis"] is False
    system = seen["payload"]["systemInstruction"]["parts"][0]["text"]
    assert "total sugars" in system and "added sugars" in system  # rule 13 explains the distinction


def test_product_question_uses_verified_context_and_additive_reference(monkeypatch):
    seen = _capture(monkeypatch)
    ctx = {"kind": "packaged", "title": "Brand X lemon drink", "status": "matched to a dataset product",
           "additives": [{"code": "INS 330", "name": "Citric acid"}]}
    r = client.post("/api/chat", json={"message": "What does E330 do in this drink?", "context": ctx})
    assert r.json()["grounded_in_analysis"] is True
    system = seen["payload"]["systemInstruction"]["parts"][0]["text"]
    assert "Brand X lemon drink" in system and "Citric acid (INS 330)" in system


def test_unknown_code_in_question_is_marked_unverifiable(monkeypatch):
    seen = _capture(monkeypatch)
    client.post("/api/chat", json={"message": "What is E1234?"})
    system = seen["payload"]["systemInstruction"]["parts"][0]["text"]
    assert "INS 1234: NOT in SmartPlateAI's reference data" in system


def test_provider_failure_falls_back_to_reference_data_for_named_additives(monkeypatch):
    monkeypatch.setattr(chat, "api_key", lambda: SECRET)

    def boom(url, payload, key):
        raise urllib.error.URLError("network down")
    monkeypatch.setattr(chat, "post_json", boom)
    monkeypatch.setattr(chat.time, "sleep", lambda s: None)
    r = client.post("/api/chat", json={"message": "What does E330 mean?"})
    j = r.json()
    assert r.status_code == 200 and j["success"] and j["answer_source"] == "reference_data" and j["provider_error"] == "CHAT_UNAVAILABLE"
    assert "Citric acid (INS 330)" in j["reply"] and "not available right now" in j["reply"]
    assert SECRET not in r.text
    # A question that names nothing in the reference data still gets the clear provider error, not an invented answer.
    r2 = client.post("/api/chat", json={"message": "Is this product good for me?"})
    assert r2.status_code == 502 and r2.json()["error_code"] == "CHAT_UNAVAILABLE" and SECRET not in r2.text


def test_malformed_provider_reply_is_handled(monkeypatch):
    monkeypatch.setattr(chat, "api_key", lambda: SECRET)
    monkeypatch.setattr(chat, "post_json", lambda url, payload, key: {"unexpected": True})
    r = client.post("/api/chat", json={"message": "How much protein is in lentils?"})
    assert r.status_code == 502 and r.json()["error_code"] == "CHAT_EMPTY_REPLY" and SECRET not in r.text
    r2 = client.post("/api/chat", json={"message": "Why is sodium benzoate added to drinks?"})
    assert r2.json()["answer_source"] == "reference_data" and "Sodium benzoate (INS 211)" in r2.json()["reply"]


def test_stream_without_provider_answers_named_topic_from_reference_data(monkeypatch):
    monkeypatch.setattr(chat, "api_key", lambda: "")
    r = client.post("/api/chat/stream", json={"message": "Can I wash the wax off an apple?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = [b for b in r.text.split("\n\n") if b.strip()]
    chunk = json.loads(events[0].split("data: ", 1)[1])["text"]
    done = json.loads(events[-1].split("data: ", 1)[1])
    assert "Wax on fruit" in chunk and done["answer_source"] == "reference_data" and done["provider_error"] == "CHAT_NOT_CONFIGURED"
    # Not named in the reference data: the existing "not configured" error is unchanged.
    r2 = client.post("/api/chat/stream", json={"message": "hi"})
    assert r2.status_code == 503 and r2.json()["error_code"] == "CHAT_NOT_CONFIGURED"


def test_internal_errors_are_not_exposed(monkeypatch):
    monkeypatch.setattr(chat, "api_key", lambda: SECRET)

    def crash(*a, **k):
        raise RuntimeError("internal detail /secret/path " + SECRET)
    monkeypatch.setattr(chat, "ask_with_metadata", crash)
    r = client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 500 and r.json()["error_code"] == "INTERNAL_ERROR"
    assert SECRET not in r.text and "secret/path" not in r.text and "Traceback" not in r.text


# ================================================================== meal planner
def _plan(*meals):
    return json.dumps({"days": [{"day": 1, "meals": list(meals)}]})


def _stub_plan(monkeypatch, text):
    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "post_json", lambda url, payload, key: {"candidates": [{"content": {"parts": [{"text": text}]}}]})


APPLE_BOWL = {"meal": "snack", "name": "Apple and banana bowl", "why": "Uses the apple you have.",
              "ingredients": [{"item": "Apple", "grams": 150}, {"item": "Banana", "grams": 100}],
              "estimated_nutrition": {"energy_kcal": 170, "protein_g": 1.5}}
DAL = {"meal": "lunch", "name": "Dal and rice", "ingredients": [{"item": "Toor dal", "grams": 50}, {"item": "Cooked rice", "grams": 150}],
       "estimated_nutrition": {"energy_kcal": 450}}


def test_plan_has_why_and_verified_nutrition_with_consistent_units(monkeypatch):
    _stub_plan(monkeypatch, _plan(APPLE_BOWL))
    a = auth_user()
    r = client.post("/api/meal-plans", headers=a, json={"days": 1, "meals": ["snack"]})
    assert r.status_code == 201, r.text
    day = r.json()["plan"]["plan"]["days"][0]
    meal = day["meals"][0]
    assert meal["why"] == "Uses the apple you have."
    v = meal["verified_nutrition"]
    assert v["status"] == "complete" and v["matched"] == 2
    ref = analyze.get_nutrition()
    apple100 = next(n for n in ref.lookup("apple")["nutrients"] if n["key"] == "energy_kcal")["per_100g"]
    banana100 = next(n for n in ref.lookup("banana")["nutrients"] if n["key"] == "energy_kcal")["per_100g"]
    rows = {x["item"]: x for x in v["ingredients"]}
    assert rows["Apple"]["values"]["energy_kcal"] == pytest.approx(apple100 * 1.5, abs=0.01)  # per 100 g scaled to 150 g
    assert v["totals"]["energy_kcal"] == pytest.approx(apple100 * 1.5 + banana100, abs=0.1)
    assert v["totals"]["sodium_mg"] == pytest.approx(sum(x["values"]["sodium_mg"] for x in v["ingredients"]), abs=0.1)  # mg with mg
    assert day["totals_verified"]["complete"] and day["totals_verified"]["totals"]["energy_kcal"] == v["totals"]["energy_kcal"]
    assert rows["Apple"]["source"]["fdc_id"] is not None


def test_unmatched_or_unweighed_ingredients_make_totals_partial_not_fabricated(monkeypatch):
    meal = {"meal": "breakfast", "name": "Apple with mystery spread",
            "ingredients": [{"item": "Apple", "grams": 100}, {"item": "Zzyzx spread", "grams": 20}, {"item": "Banana", "grams": None}],
            "estimated_nutrition": {"energy_kcal": 200}}
    _stub_plan(monkeypatch, _plan(meal))
    r = client.post("/api/meal-plans", headers=auth_user(), json={"days": 1, "meals": ["breakfast"]})
    day = r.json()["plan"]["plan"]["days"][0]
    v = day["meals"][0]["verified_nutrition"]
    assert v["status"] == "partial" and v["matched"] == 1 and v["total"] == 3
    statuses = {x["item"]: x["status"] for x in v["ingredients"]}
    assert statuses == {"Apple": "matched", "Zzyzx spread": "unavailable", "Banana": "no_amount"}
    assert all(x["values"] is None for x in v["ingredients"] if x["status"] != "matched")
    assert day["totals_verified"]["complete"] is False and day["totals_verified"]["totals"]["energy_kcal"] is None


def test_usda_lookup_is_used_for_other_ingredients_without_network(monkeypatch):
    monkeypatch.setattr(usda, "enabled", lambda: True)
    calls = []

    def fake_lookup(name, category, serving_grams=None):
        calls.append(name)
        if name == "toor dal":
            return {"status": "found", "nutrition": {"source_fdc_id": 1, "matched_description": "Pigeon peas, mature seeds, raw",
                                                    "data_type": "SR Legacy", "source_url": "https://fdc.nal.usda.gov/food-details/1/nutrients",
                                                    "nutrients": [{"key": "energy_kcal", "label": "Energy", "unit": "kcal", "per_100g": 343.0},
                                                                  {"key": "protein_g", "label": "Protein", "unit": "g", "per_100g": 21.7}]}}
        return {"status": "no_match", "message": "No verified USDA reference record clearly matches."}
    monkeypatch.setattr(usda, "lookup", fake_lookup)
    refs = meal_nutrition.resolve_all(["Toor dal", "Cooked rice", "toor dal"], None)
    assert sorted(calls) == ["cooked rice", "toor dal"]  # each distinct name looked up once
    v = meal_nutrition.meal_verified({"ingredients": [{"item": "Toor dal", "grams": 50}, {"item": "Cooked rice", "grams": 150}]}, refs)
    assert v["status"] == "partial"
    dal = v["ingredients"][0]
    assert dal["values"]["energy_kcal"] == pytest.approx(171.5) and dal["values"]["carbohydrate_g"] is None  # missing stays None
    assert dal["source"]["description"].startswith("Pigeon peas")


def test_declared_allergen_meal_is_withheld_and_replacement_targets_only_that_meal(monkeypatch):
    a = auth_user()
    client.put("/api/allergens/preferences", headers=a, json={"allergens": [{"allergen": "peanut", "severity": "severe"}]})
    peanut = {"meal": "breakfast", "name": "Peanut poha", "ingredients": [{"item": "Poha", "grams": 60}, {"item": "Peanuts", "grams": 15}],
              "estimated_nutrition": {"energy_kcal": 320}}
    _stub_plan(monkeypatch, _plan(peanut, DAL))
    plan = client.post("/api/meal-plans", headers=a, json={"days": 1, "meals": ["breakfast", "lunch"]}).json()["plan"]
    meals = {m["meal"]: m for m in plan["plan"]["days"][0]["meals"]}
    assert meals["breakfast"]["withheld"] and meals["breakfast"]["verified_nutrition"] is None
    assert not any(i["item"] == "peanuts" for i in plan["plan"]["shopping_list"])
    lunch_before = meals["lunch"]
    _stub_plan(monkeypatch, _plan({"meal": "breakfast", "name": "Vegetable upma", "ingredients": [{"item": "Semolina", "grams": 60}],
                                   "estimated_nutrition": {"energy_kcal": 280}, "why": "No peanuts."}))
    after = client.post(f"/api/meal-plans/{plan['id']}/regenerate", headers=a, json={"day": 1, "meal": "breakfast"}).json()["plan"]
    m2 = {m["meal"]: m for m in after["plan"]["days"][0]["meals"]}
    assert m2["breakfast"]["name"] == "Vegetable upma" and not m2["breakfast"]["withheld"]
    assert m2["lunch"]["name"] == lunch_before["name"] and m2["lunch"]["ingredients"] == lunch_before["ingredients"]
    # Saved plans reload with the same content.
    again = client.get(f"/api/meal-plans/{plan['id']}", headers=a).json()["plan"]
    assert again["plan"]["days"] == after["plan"]["days"]


def test_target_is_optional_validated_and_kept(monkeypatch):
    _stub_plan(monkeypatch, _plan(APPLE_BOWL))
    a = auth_user()
    bad = client.post("/api/meal-plans", headers=a, json={"days": 1, "target_kcal_per_day": 600})
    assert bad.status_code == 422 and bad.json()["error_code"] == "TARGET_OUT_OF_RANGE" and "dietitian" in bad.json()["message"]
    ok = client.post("/api/meal-plans", headers=a, json={"days": 1, "target_kcal_per_day": 1800}).json()["plan"]
    assert ok["plan"]["target_kcal_per_day"] == 1800 and "1800 kcal/day" in ok["title"]
    none = client.post("/api/meal-plans", headers=a, json={"days": 1}).json()["plan"]
    assert "target_kcal_per_day" not in none["plan"]


def test_empty_or_failed_generation_is_reported_and_nothing_is_saved(monkeypatch):
    a = auth_user()
    before = len(client.get("/api/meal-plans", headers=a).json()["items"])
    _stub_plan(monkeypatch, json.dumps({"days": []}))
    r = client.post("/api/meal-plans", headers=a, json={"days": 1})
    assert r.status_code == 502 and r.json()["error_code"] == "PLAN_INVALID"
    monkeypatch.setattr(chat.time, "sleep", lambda s: None)

    def down(url, payload, key):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(chat, "post_json", down)
    r2 = client.post("/api/meal-plans", headers=a, json={"days": 1})
    assert r2.status_code == 502 and r2.json()["error_code"] == "CHAT_UNAVAILABLE"
    assert len(client.get("/api/meal-plans", headers=a).json()["items"]) == before


def test_planner_prompt_asks_for_reasons_specific_ingredients_and_no_health_promises(monkeypatch):
    seen = {}

    def fake(url, payload, key):
        seen["text"] = payload["contents"][0]["parts"][0]["text"]
        return {"candidates": [{"content": {"parts": [{"text": _plan(APPLE_BOWL)}]}}]}
    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "post_json", fake)
    client.post("/api/meal-plans", headers=auth_user(), json={"days": 1, "target_kcal_per_day": 2000})
    t = " ".join(seen["text"].split())
    assert '"why"' in t and "including its state" in t
    assert "promise health or weight outcomes" in t and '"target_kcal_per_day": 2000' in t
