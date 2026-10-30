"""Category foods (Sandwich, Burger, ...): the image model recognises the category only, so a paneer sandwich must never be
shown the nutrition of the class's single USDA record (a chicken submarine sandwich) as if it were its own.

Uses the real NutritionReference on a small SYNTHETIC CSV that carries the real fdc_ids of the production dataset (values are
placeholders). The image model, OpenAI/Gemini and USDA FoodData Central are MOCKED: these tests check the decision rules and
the response contract, not recognition accuracy."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.routes import analyze
from app.data import class_references as cr
from app.main import app
from app.services import usda
from app.services.nutrition import NutritionReference

SUB = "Fast foods, submarine sandwich, oven roasted chicken on white bread with lettuce and tomato"


@pytest.fixture
def ref(tmp_path):
    p = tmp_path / "food.csv"
    p.write_text("food,fdc_id,energy_kcal,protein_g\n"
                 "Sandwich,170309,157,10.84\nSandwich,170309,157,10.84\nApple,171688,52,0.26\nBurger,999,297,16.5\n", encoding="utf-8")
    return NutritionReference(p)


class Rec:
    class_names = ["Apple", "Burger", "Sandwich"]
    ready, status_message, thresholds = True, "ready", None

    def __init__(self, food="Sandwich", score=0.95, decision="accept"):
        self.food, self.score, self.decision = food, score, decision

    def load(self):
        return True

    def analyze_image(self, img):
        others = [c for c in self.class_names if c != self.food]
        top = [{"class_id": self.class_names.index(self.food), "food": self.food, "score": self.score},
               *[{"class_id": self.class_names.index(c), "food": c, "score": 0.01} for c in others]]
        return {"decision": self.decision, "reason": None if self.decision == "accept" else "low_confidence", "calibrated": True,
                "confidence": self.score, "margin": self.score - 0.01, "top_k": top, "features": None,
                "freshness": {"status": "not_assessed", "confidence": None, "message": "x"}, "signals": {}}


def provider(status, name=None, supported=None):
    return {"status": status, "food_name": name, "named_as": name, "supported_food": supported, "visible_evidence": [],
            "uncertainty": None, "category": "Cooked Dishes", "provider": "Google Gemini"}


@pytest.fixture
def env(monkeypatch, ref):
    state = {"rec": Rec(), "oa": provider("recognized", "Sandwich", "Sandwich"), "usda": {}}
    app.dependency_overrides[analyze.get_recognizer] = lambda: state["rec"]
    app.dependency_overrides[analyze.get_nutrition] = lambda: ref
    monkeypatch.setattr(analyze, "run_openai_vision", lambda img, names: dict(state["oa"]))
    monkeypatch.setattr(analyze, "run_vision", lambda *a: None)
    monkeypatch.setattr(usda, "lookup", lambda food, category, serving=None: state["usda"].get(
        food, {"status": "no_match", "message": f"No verified USDA reference record clearly matches '{food}', so nutrition is not shown."}))
    yield state
    app.dependency_overrides.clear()


def photo():
    b = io.BytesIO()
    Image.new("RGB", (64, 64), (190, 150, 90)).save(b, "PNG")
    return b.getvalue()


def analyse(c=None):
    return (c or TestClient(app)).post("/api/analyze/food", files={"file": ("p.png", photo(), "image/png")}).json()


# ------------------------------------------------------------------ the record behind each class is named
def test_reference_names_the_actual_usda_record(ref):
    s = ref.lookup("Sandwich")
    assert SUB in s["basis"] and s["basis"].startswith("per 100 g (USDA") and s["matched_description"] == SUB
    assert s["generic_category_reference"] is True and "specific type was not determined" in s["note"]
    assert "chicken submarine sandwich" in s["note"] and s["source_url"].endswith("/170309/nutrients")
    a = ref.lookup("Apple")
    assert a["matched_description"].startswith("Apples, raw") and a["generic_category_reference"] is False
    b = ref.lookup("Burger")  # dataset id differs from the verified one: no description is claimed
    assert b["matched_description"] is None and b["basis"] == "per 100 g (USDA FoodData Central reference record)"


# ------------------------------------------------------------------ analysis: category recognised, type not determined
def test_sandwich_is_a_category_and_nutrition_waits_for_the_type(env):
    j = analyse()
    assert j["success"] and j["prediction"]["food"] == "Sandwich"
    assert j["identification"]["specificity"] == "category" and j["identification"]["specific_type"] is None
    assert j["nutrition"] is None and "cannot tell which kind" in j["nutrition_error"] and SUB in j["nutrition_error"]
    ch = j["nutrition_choice"]
    assert ch["category"] == "Sandwich" and ch["specific_type"] is None and "Paneer sandwich" in ch["options"]
    assert ch["generic_reference"]["description"] == SUB and ch["generic_reference"]["fdc_id"] == 170309


def test_specific_foods_keep_their_nutrition(env):
    env["rec"], env["oa"] = Rec("Apple"), provider("recognized", "Apple", "Apple")
    j = analyse()
    assert j["nutrition"]["matched_description"].startswith("Apples, raw") and j["nutrition_choice"] is None
    assert j["identification"]["specificity"] == "specific" and j["identification"]["specific_type"] == "Apple"


def test_paneer_sandwich_named_by_provider_is_never_given_the_class_record(env):
    env["oa"] = provider("unsupported_food", "Paneer sandwich")
    j = analyse()  # model is 95% sure of the category: the user is asked, the provider's specific name offered first
    assert j["error_code"] == "LOW_CONFIDENCE" and j["general_candidate"]["food"] == "Paneer sandwich" and "nutrition" not in j
    env["rec"] = Rec("Sandwich", score=0.62)  # model not sure: the provider's specific identification is used
    j = analyse()
    assert j["prediction"]["food"] == "Paneer sandwich" and j["nutrition"] is None  # USDA has no paneer-sandwich record
    assert "not specific to paneer sandwich" in j["nutrition_error"]
    assert j["generic_alternative"]["food"] == "Sandwich" and j["generic_alternative"]["description"] == SUB


def test_provider_outage_still_never_applies_the_generic_record(env):
    env["oa"] = {"status": "unavailable", "reason": "quota_exhausted", "provider": "OpenAI Vision"}
    j = analyse()
    assert j["success"] and j["nutrition"] is None and j["nutrition_choice"]["options"]


# ------------------------------------------------------------------ the user's choice
def test_choosing_the_category_alone_does_not_accept_the_generic_record(env):
    c = TestClient(app)
    pid = analyse(c)["image_ref"]
    j = c.post("/api/analyze/confirm", json={"food": "Sandwich", "pending_id": pid}).json()
    assert j["nutrition"] is None and j["nutrition_choice"]["category"] == "Sandwich"
    g = c.post("/api/analyze/confirm", json={"food": "Sandwich", "pending_id": pid, "accept_generic": True}).json()
    assert g["confirmation"]["accepted_generic_reference"] is True and g["identification"]["specific_type"] is None
    assert g["nutrition"]["matched_description"] == SUB and "Generic reference" in g["nutrition"]["note"]


def test_specific_type_with_a_usda_record_gets_that_record(env):
    env["usda"]["Cheese sandwich"] = {"status": "found", "nutrition": {
        "basis": "per 100 g by weight (USDA FoodData Central Survey (FNDDS): Cheese sandwich, NFS)", "matched_description": "Cheese sandwich, NFS",
        "source_fdc_id": 2706291, "nutrients": [{"key": "energy_kcal", "label": "Energy", "unit": "kcal", "per_100g": 297.0, "per_serving": None}],
        "not_available": [], "is_estimate": True, "note": "x", "serving_grams": None, "serving_note": "x"}}
    c = TestClient(app)
    pid = analyse(c)["image_ref"]
    j = c.post("/api/analyze/confirm", json={"food": "Cheese sandwich", "pending_id": pid}).json()
    assert j["nutrition"]["matched_description"] == "Cheese sandwich, NFS" and j["generic_alternative"] is None


def test_specific_type_without_a_usda_record_says_so_and_offers_the_generic(env):
    c = TestClient(app)
    pid = analyse(c)["image_ref"]
    j = c.post("/api/analyze/confirm", json={"food": "Paneer sandwich", "pending_id": pid}).json()
    assert j["nutrition"] is None and "No verified USDA reference record" in j["nutrition_error"]
    assert j["generic_alternative"] == {"food": "Sandwich", "description": SUB, "fdc_id": 170309,
                                        "caveat": cr.GENERIC_CAVEATS["Sandwich"]}


# ------------------------------------------------------------------ data module
@pytest.mark.parametrize("name,cls", [("Paneer sandwich", "Sandwich"), ("grilled cheese sandwich", "Sandwich"), ("Veggie burger", "Burger"),
                                      ("Hamburger", "Burger"), ("Glazed doughnut", "Donut"), ("Hot dogs", "Hot Dog"), ("Paneer", None),
                                      ("Apple pie", None), (None, None)])
def test_category_for_name(name, cls):
    assert cr.category_for_name(name) == cls


def test_every_category_has_variants_and_a_caveat_and_every_class_a_record():
    import json
    from pathlib import Path
    names = json.loads((Path(__file__).resolve().parents[1] / "models" / "production" / "food_classifier" / "class_names.json")
                       .read_text(encoding="utf-8"))["class_names"] if (Path(__file__).resolve().parents[1] / "models" / "production" /
                                                                       "food_classifier" / "class_names.json").is_file() else list(cr.CLASS_RECORDS)
    assert set(cr.CLASS_RECORDS) == set(names)
    assert set(cr.CATEGORY_VARIANTS) == set(cr.GENERIC_CAVEATS) and set(cr.CATEGORY_VARIANTS) <= set(names)


# ------------------------------------------------------------------ USDA matcher: a different dish is never "the food"
@pytest.mark.parametrize("description,food", [
    ("Rice, fried, with chicken", "Fried chicken"),
    ("Pizza, cheese, with fruit, medium crust", "Cheese pizza"),
    ("Taco or tostada salad with chicken", "Chicken taco"),
    ("Frankfurters or hot dogs and sauerkraut", "Frankfurter"),
])
def test_matcher_rejects_records_of_a_different_dish(description, food):
    score = usda.match_score(description, "Survey (FNDDS)", food, produce=False)
    assert score is None or score[0] >= usda.MAX_PENALTY


@pytest.mark.parametrize("description,food", [("Cheese sandwich, NFS", "Cheese sandwich"), ("Taquito, chicken", "Chicken taquito"),
                                              ("Taco, with beans, no cheese", "Bean taco"), ("Cheese, paneer", "Paneer"),
                                              ("Pizza with pepperoni, stuffed crust", "Pepperoni pizza")])
def test_matcher_keeps_real_matches(description, food):
    score = usda.match_score(description, "Survey (FNDDS)", food, produce=False)
    assert score is not None and score[0] < usda.MAX_PENALTY
