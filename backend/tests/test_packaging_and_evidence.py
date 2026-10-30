"""Packaged products and weak food evidence.

Rule A: ImageNet's top class is a generic container AND the food signal is below the calibrated floor -> PACKAGED_PRODUCT
        ("use the label scanner"), never a food name, nutrition or "not food".
Rule B: the 24-class model accepted a food, nothing independent verified it, and the food signal is below the floor ->
        ask the user to confirm (LOW_CONFIDENCE, reason weak_food_evidence). Never turned into "non-food".
Both apply only when no vision provider identified anything. No new threshold: ImageNet top-1 and the existing floor.

Part A uses a fake recognizer (no TensorFlow); provider answers are MOCKED. Part B runs the REAL model on REAL photos
(Open Food Facts package fronts, Openverse photos, held-out test photos) through the API with every paid provider off."""
import csv
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.routes import analyze
from app.main import app
from app.ml.imagenet_groups import CONTAINER, PRODUCT, group_of
from app.ml.recognizer import IMAGENET_FOOD_INDICES, EmbedResult
from app.ml.rejection import Thresholds

FLOOR = 0.0298
UNAVAILABLE = {"status": "unavailable", "reason": "quota_exhausted", "provider": "OpenAI Vision"}


def provider(status, name=None, supported=None):
    return {"status": status, "food_name": name, "named_as": name, "supported_food": supported, "visible_evidence": [],
            "uncertainty": None, "category": None, "provider": "Google Gemini"}


class Rec:
    class_names = ["Apple", "Donut", "Fries", "Sandwich"]
    thresholds = Thresholds(food_mass_low=FLOOR, maha_high=2477.0, conf_min=0.574, margin_min=0.244)
    ready, status_message = True, "ready"

    def __init__(self, food="Fries", score=0.98, decision="accept", food_mass=0.005, group="container"):
        self.food, self.score, self.decision, self.fm, self.group = food, score, decision, food_mass, group

    def load(self):
        return True

    def analyze_image(self, img):
        others = [c for c in self.class_names if c != self.food]
        top = [{"class_id": self.class_names.index(self.food), "food": self.food, "score": self.score},
               *[{"class_id": self.class_names.index(c), "food": c, "score": 0.005} for c in others]]
        return {"decision": self.decision, "reason": {"accept": None, "uncertain": "low_confidence"}.get(self.decision, "far_from_supported_foods"),
                "calibrated": True, "confidence": self.score, "margin": self.score - 0.005, "top_k": top, "features": None,
                "freshness": {"status": "fresh", "confidence": 0.9},
                "packaged_product": self.group == "container" and self.fm < FLOOR,
                "signals": {"imagenet_food_mass": self.fm, "feature_distance": 2000.0, "imagenet_group": self.group}}


@pytest.fixture
def env(monkeypatch):
    state = {"rec": Rec(), "oa": UNAVAILABLE}
    app.dependency_overrides[analyze.get_recognizer] = lambda: state["rec"]
    monkeypatch.setattr(analyze, "run_openai_vision", lambda img, names: dict(state["oa"]))
    monkeypatch.setattr(analyze, "run_vision", lambda *a: None)
    monkeypatch.setattr(analyze, "openai_outage_needs_confirmation", lambda reason, conf: False)  # isolate the rules under test
    yield state
    app.dependency_overrides.clear()


def analyse():
    b = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 160, 60)).save(b, "PNG")
    return TestClient(app).post("/api/analyze/food", files={"file": ("p.png", b.getvalue(), "image/png")}).json()


def no_food_data(j):
    assert not {"prediction", "nutrition", "nutrition_choice", "candidates", "freshness"} & j.keys()
    assert "fries" not in json.dumps(j).lower() and "donut" not in json.dumps(j).lower()


# ------------------------------------------------------------------ Part A: rules
def test_chips_packet_called_fries_goes_to_the_label_scanner(env):
    j = analyse()  # 98% "Fries", ImageNet: packet, food signal 0.005
    assert j["error_code"] == "PACKAGED_PRODUCT" and j["suggest_packaged_scan"] is True
    assert j["reason"] == "package_without_food_evidence" and j["recognition"]["status"] == "packaged_product"
    no_food_data(j)


@pytest.mark.parametrize("decision", ["non_food", "uncertain"])
def test_package_is_not_called_non_food_or_left_as_a_food_guess(env, decision):
    env["rec"] = Rec(decision=decision, score=0.4)
    assert analyse()["error_code"] == "PACKAGED_PRODUCT"


def test_a_provider_answer_takes_precedence_over_the_package_route(env):
    env["oa"] = provider("no_food")  # e.g. a medicine carton: the provider says there is no food
    assert analyse()["error_code"] == "NON_FOOD_IMAGE"
    env["oa"] = provider("unsupported_food", "Lay's Classic Salted potato chips")
    j = analyse()
    assert j.get("error_code") != "PACKAGED_PRODUCT" and "Fries" not in json.dumps(j.get("prediction") or {})


def test_non_food_product_group_is_never_routed_as_a_package(env):
    env["rec"] = Rec(decision="non_food", score=0.3, group="product")  # pill bottle, lotion, phone ...
    assert analyse()["error_code"] == "NON_FOOD_IMAGE"


def test_genuine_fries_are_shown_with_nutrition(env):
    env["rec"] = Rec(food_mass=0.62, group="food")
    j = analyse()
    assert j["success"] and j["prediction"]["food"] == "Fries" and j.get("nutrition_choice") is None


def test_confident_food_with_no_food_evidence_asks_instead_of_showing_nutrition(env):
    env["rec"] = Rec(food="Donut", score=0.71, food_mass=0.0126, group="product")  # a phone the model calls "Donut"
    j = analyse()
    assert j["error_code"] == "LOW_CONFIDENCE" and j["reason"] == "weak_food_evidence" and j["requires_confirmation"]
    assert "little visual evidence of food" in j["message"] and "nutrition" not in j
    assert j["candidates"][0]["food"] == "Donut"  # the guess is offered for confirmation, labelled as such


def test_weak_evidence_is_not_counted_as_non_food(env):
    env["rec"] = Rec(food="Apple", score=0.99, food_mass=0.001, group="other")
    assert analyse()["error_code"] == "LOW_CONFIDENCE"  # never NON_FOOD_IMAGE on low evidence alone


def test_an_independent_identification_resolves_weak_evidence(env):
    env["rec"] = Rec(food="Apple", score=0.95, food_mass=0.01, group="other")
    env["oa"] = provider("recognized", "Apple", "Apple")
    j = analyse()
    assert j["success"] and j["prediction"]["food"] == "Apple"


def test_food_signal_at_the_floor_is_enough(env):
    env["rec"] = Rec(food="Apple", score=0.95, food_mass=FLOOR, group="other")
    assert analyse()["success"]  # the floor itself is not "below the floor"


def test_sandwich_keeps_the_category_choice(env):
    env["rec"] = Rec(food="Sandwich", score=0.95, food_mass=0.5, group="food")
    j = analyse()
    assert j["success"] and j["nutrition_choice"]["category"] == "Sandwich" and j["nutrition"] is None


def test_groups_come_from_imagenet_class_meanings():
    assert group_of(692, IMAGENET_FOOD_INDICES) == "container"  # packet
    assert group_of(720, IMAGENET_FOOD_INDICES) == "product"  # pill bottle
    assert group_of(963, IMAGENET_FOOD_INDICES) == "food"  # pizza
    assert group_of(1, IMAGENET_FOOD_INDICES) == "other"
    assert not set(CONTAINER) & set(PRODUCT) and not (set(CONTAINER) | set(PRODUCT)) & set(IMAGENET_FOOD_INDICES)


def test_embed_result_still_unpacks_as_three_values():
    r = EmbedResult((1, 2, 3), imagenet="x")
    a, b, c = r
    assert (a, b, c) == (1, 2, 3) and r.imagenet == "x" and len(r) == 3


# ------------------------------------------------------------------ Part B: real model, real photos, providers off
BACKEND = Path(__file__).resolve().parents[1]
needs_model = pytest.mark.skipif(not (BACKEND / "models" / "production" / "food_classifier" / "best.keras").is_file(),
                                 reason="production model not installed")


@pytest.fixture(scope="module")
def real():
    from app.ml.recognizer import FoodRecognizer
    rec = FoodRecognizer()
    assert rec.load(), rec.status_message
    return rec


@pytest.fixture
def real_api(real, monkeypatch):
    app.dependency_overrides[analyze.get_recognizer] = lambda: real
    monkeypatch.setattr(analyze, "run_openai_vision", lambda img, names: dict(UNAVAILABLE))  # no provider answers
    monkeypatch.setattr(analyze, "run_vision", lambda *a: None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def post(c, path: Path):
    return c.post("/api/analyze/food", files={"file": (path.name, path.read_bytes(), "image/jpeg")}).json()


def photos(folder: str) -> list[tuple[Path, str]]:
    d = BACKEND / folder
    f = d / "ATTRIBUTION.csv"
    if not f.is_file():
        pytest.skip(f"NOT RUN: {folder} has no ATTRIBUTION.csv")
    return [(d / r["file"], r["category"]) for r in csv.DictReader(open(f, encoding="utf-8"))]


@needs_model
def test_real_lays_packet_is_never_shown_as_fries(real_api):
    lays = BACKEND / "data_eval" / "packaged" / "8901491101837" / "front.jpg"
    if not lays.is_file():
        pytest.skip("NOT RUN: Lay's test photo missing")
    j = post(real_api, lays)
    assert not j.get("success") and j["error_code"] in ("PACKAGED_PRODUCT", "LOW_CONFIDENCE"), j.get("error_code")


@needs_model
@pytest.mark.parametrize("folder", ["data_nonfood/general", "data_nonfood/packaged_objects"])
def test_real_non_food_is_never_shown_as_a_food(real_api, folder):
    shown = [(p.name, post(real_api, p).get("prediction", {}).get("food")) for p, _ in photos(folder)]
    shown = [s for s in shown if s[1]]
    print(f"\n{folder}: shown as a food: {shown}")
    assert not shown  # measured 2026-10-27: 2/64 and 3/27 before the rules, 0 after


@needs_model
def test_real_package_fronts_are_rarely_called_non_food(real_api):
    man = BACKEND / "data_eval" / "packaged" / "MANIFEST.json"
    if not man.is_file():
        pytest.skip("NOT RUN: packaged evaluation set missing")
    codes = {}
    for p in json.loads(man.read_text(encoding="utf-8")):
        j = post(real_api, BACKEND / "data_eval" / "packaged" / p["barcode"] / "front.jpg")
        codes[p["barcode"]] = j.get("error_code") or "food_shown:" + str((j.get("prediction") or {}).get("food"))
    vals = list(codes.values())
    print(f"\npackage fronts ({len(vals)}): " + json.dumps({k: vals.count(k) for k in set(vals)}))
    assert vals.count("NON_FOOD_IMAGE") <= len(vals) // 2  # measured: 19/29 before, 9/29 after (a regression floor, not a goal)
    assert vals.count("PACKAGED_PRODUCT") >= len(vals) // 3  # measured: 16/29 after


@needs_model
def test_real_supported_foods_rarely_need_an_extra_confirmation(real_api):
    import pandas as pd
    m = pd.read_csv(BACKEND / "data_prep" / "split_manifest.csv", low_memory=False)
    t = m[(m.new_split == "test") & (~m.is_augmented_copy.astype(bool))]
    items = [(Path(p), f) for f, g in t.groupby("food") for p in g.sample(min(len(g), 5), random_state=3).image_path]
    out = {"shown_correct": 0, "weak_evidence": 0, "packaged": 0, "non_food": 0, "other": 0}
    for p, food in items:
        j = post(real_api, p)
        if j.get("success") and j["prediction"]["food"] == food:
            out["shown_correct"] += 1
        elif j.get("reason") == "weak_food_evidence":
            out["weak_evidence"] += 1
        elif j.get("error_code") == "PACKAGED_PRODUCT":
            out["packaged"] += 1
        elif j.get("error_code") == "NON_FOOD_IMAGE":
            out["non_food"] += 1
        else:
            out["other"] += 1
    print(f"\nheld-out supported photos ({len(items)}): {out}")
    assert out["packaged"] + out["weak_evidence"] <= 0.08 * len(items)  # measured on 360 photos: see PACKAGED_EVALUATION.md
    assert out["shown_correct"] >= 0.80 * len(items)
