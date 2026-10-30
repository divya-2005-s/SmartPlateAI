"""Food identity vs freshness vs nutrition, image quality, and the condition-classifier connection.

The CSV and model outputs below are SYNTHETIC test fixtures (no real dataset or trained model is used); external
services are mocked. These tests check behaviour and contracts, not real-world accuracy."""
import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from app.api.routes import analyze
from app.main import app
from app.ml import condition as C
from app.ml import condition_eval as E
from app.ml import image_quality as Q
from app.services import openai_vision, usda, vision
from app.services.nutrition import NutritionReference
from tests.test_recognition_packaged_history_fixes import FakeRecognizer, png

# ------------------------------------------------------------------ nutrition record selection
CSV = """food,fdc_id,condition,split,energy_kcal,protein_g,carbohydrate_g,vitamin_c_mg
Banana,999999,rotten,train,70,0.5,18.0,
banana,173944,fresh,train,89,1.09,22.84,8.7
Banana,173944,fresh,val,89,1.09,22.84,8.7
Banana ,173944,rotten,test,89,1.09,22.84,8.7
Apple,171688,fresh,train,52,0.26,13.81,4.6
"""


@pytest.fixture
def ref(tmp_path):
    p = tmp_path / "food.csv"
    p.write_text(CSV, encoding="utf-8")
    return NutritionReference(p)


def test_one_deterministic_record_per_food_regardless_of_row_order_or_condition(ref):
    a = ref.lookup("Banana", 100)
    b = ref.lookup("banana", 100)
    assert a == b  # same food, same serving -> identical output, also case-insensitive
    vals = {n["key"]: n["per_100g"] for n in a["nutrients"]}
    # rule: the FDC record used by most rows (173944), not the first row in the file (a 'rotten' row with other values)
    assert a["source_fdc_id"] == 173944 and vals["energy_kcal"] == 89 and vals["protein_g"] == 1.09
    assert a["reference"]["rows_for_food"] == 4 and a["reference"]["distinct_profiles_in_dataset"] == 2
    assert ref.conflicts == {"Banana": 2}


def test_serving_scaling_and_missing_values(ref):
    n = {x["key"]: x for x in ref.lookup("Apple", 150)["nutrients"]}
    assert n["energy_kcal"]["per_serving"] == pytest.approx(78.0) and n["protein_g"]["per_serving"] == pytest.approx(0.39)
    assert ref.lookup("Apple", None)["nutrients"][0]["per_serving"] is None  # no serving given -> nothing invented
    assert ref.lookup("Mango", 100) is None
    banana = {x["key"]: x for x in ref.lookup("Banana", 100)["nutrients"]}
    assert banana["vitamin_c_mg"]["per_100g"] == 8.7


def test_condition_words_do_not_change_the_food():
    assert openai_vision.class_for_name("Rotten Banana", ["Banana", "Apple"]) == "Banana"
    assert openai_vision.class_for_name("overripe bananas", ["Banana"]) == "Banana"
    assert openai_vision.strip_condition("Mouldy Mango") == "Mango"
    assert openai_vision.strip_condition("Dried apricot") == "Dried apricot"  # a different food stays different


# ------------------------------------------------------------------ API: same food, different freshness
class RealishNutrition:
    def __init__(self, ref):
        self.ref, self.error = ref, None

    def lookup(self, food, serving=None):
        return self.ref.lookup(food, serving)


FRESH = {"status": "fresh", "confidence": 0.94, "model": "condition_classifier", "model_status": "ready", "message": "Looks fresh."}
ROTTEN = {"status": "possibly_spoiled", "confidence": 0.91, "model": "condition_classifier", "model_status": "ready", "message": "Rotten."}


@pytest.fixture
def api(monkeypatch, ref):
    rec = FakeRecognizer(food="Banana", score=0.95)
    rec.class_names = ["Apple", "Banana", "Tomato", "Onion"]
    app.dependency_overrides[analyze.get_recognizer] = lambda: rec
    app.dependency_overrides[analyze.get_nutrition] = lambda: RealishNutrition(ref)
    monkeypatch.setattr(vision, "enabled", lambda: False)
    monkeypatch.setattr(openai_vision, "availability", lambda: "not_configured")
    state = {"cond": FRESH}
    monkeypatch.setattr(analyze, "run_condition", lambda img, q, is_food: state["cond"])
    yield state, rec, monkeypatch
    app.dependency_overrides.clear()


def post(c, image=None, grams=None):
    data = {"serving_grams": str(grams)} if grams else {}
    return c.post("/api/analyze/food", files={"file": ("f.png", image or png("yellow"), "image/png")}, data=data)


def test_fresh_and_rotten_banana_get_identical_reference_nutrition(api):
    state, _, _ = api
    c = TestClient(app)
    fresh = post(c, grams=120).json()
    state["cond"] = ROTTEN
    rotten = post(c, grams=120).json()
    assert fresh["prediction"]["food"] == rotten["prediction"]["food"] == "Banana"
    assert fresh["freshness"]["status"] == "fresh" and rotten["freshness"]["status"] == "possibly_spoiled"
    assert fresh["nutrition"]["nutrients"] == rotten["nutrition"]["nutrients"]  # freshness never alters nutrients
    assert fresh["nutrition"]["source_fdc_id"] == rotten["nutrition"]["source_fdc_id"] == 173944
    assert any("not lowered or changed" in n for n in rotten["notes"]) and not any("not lowered" in n for n in fresh["notes"])


def test_repeated_requests_are_deterministic(api):
    c = TestClient(app)
    a, b = post(c, grams=100).json(), post(c, grams=100).json()
    assert a["nutrition"] == b["nutrition"]


def test_freshness_from_the_photo_survives_a_food_correction(api):
    state, rec, _ = api
    rec.decision, rec.reason = "uncertain", "low_confidence"
    rec.score = 0.6  # below the destination API's automatic >70% low-score acceptance gate
    state["cond"] = ROTTEN
    c = TestClient(app)
    low = post(c).json()
    assert low["error_code"] == "LOW_CONFIDENCE" and low["freshness"]["status"] == "possibly_spoiled"
    conf = c.post("/api/analyze/confirm", json={"food": "banana", "pending_id": low["pending_id"]}).json()
    assert conf["success"] and conf["identification"]["food"] == "Banana" and conf["freshness"]["status"] == "possibly_spoiled"
    assert conf["nutrition"]["source_fdc_id"] == 173944


# ------------------------------------------------------------------ image quality
def photo(size=900, blur=0.0, bright=1.0):
    img = Image.new("RGB", (size, int(size * 0.75)), (120, 95, 70))  # wooden table
    d = ImageDraw.Draw(img)
    d.ellipse([size * 0.3, size * 0.15, size * 0.7, size * 0.55], fill=(230, 190, 40), outline=(90, 60, 10), width=5)
    for i in range(0, size, 40):
        d.line([(i, int(size * 0.6)), (i + 30, int(size * 0.7))], fill=(120, 100, 80), width=3)  # table texture
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return ImageEnhance.Brightness(img).enhance(bright)


@pytest.mark.real_quality
def test_quality_levels():
    assert Q.assess(photo())["level"] == "good"
    assert "blurry" in Q.assess(photo(blur=8))["issues"]
    dark = Q.assess(photo(bright=0.15))
    assert "too_dark" in dark["issues"] and dark["enhanceable"]
    assert "too_small" in Q.assess(photo(size=120))["issues"] and Q.assess(photo(size=120))["level"] == "poor"


def test_enhanced_result_is_used_only_when_it_confirms_the_same_food():
    orig = {"decision": "uncertain", "top_k": [{"food": "Banana"}]}
    assert Q.choose(orig, {"decision": "accept", "top_k": [{"food": "Banana"}]})[1] == "enhanced"
    assert Q.choose(orig, {"decision": "accept", "top_k": [{"food": "Apple"}]})[1] == "original"  # never a new food
    assert Q.choose({"decision": "accept", "top_k": [{"food": "Banana"}]}, {"decision": "accept", "top_k": [{"food": "Banana"}]})[1] == "original"


@pytest.mark.real_quality
def test_poor_photo_is_never_confidently_classified(api):
    buf = io.BytesIO()
    photo(size=120).save(buf, "PNG")
    r = post(TestClient(app), image=buf.getvalue())
    j = r.json()
    assert r.status_code == 422 and j["error_code"] == "LOW_CONFIDENCE" and j["reason"] == "poor_image_quality"
    assert j["image_quality"]["level"] == "poor" and "nutrition" not in j


@pytest.mark.real_quality
def test_dark_photo_gets_one_enhanced_retry(api):
    _, rec, mp = api
    calls = []

    def analyze_image(img):
        calls.append(float(np.asarray(img.convert("L")).mean()))
        dec = "accept" if len(calls) > 1 else "uncertain"
        return {"decision": dec, "reason": None if dec == "accept" else "low_confidence", "calibrated": True, "confidence": 0.9,
                "margin": 0.6, "top_k": [{"class_id": 1, "food": "Banana", "score": 0.9}, {"class_id": 0, "food": "Apple", "score": 0.05}],
                "signals": {}, "freshness": {"status": "not_assessed", "confidence": None, "message": "x"}}
    mp.setattr(rec, "analyze_image", analyze_image)
    buf = io.BytesIO()
    photo(bright=0.2).save(buf, "PNG")
    j = post(TestClient(app), image=buf.getvalue()).json()
    assert len(calls) == 2 and calls[1] > calls[0]  # second call saw the brightened copy
    assert j["enhancement"] == {"applied": True, "used": "enhanced", "for": j["image_quality"]["issues"]}
    assert j["prediction"]["food"] == "Banana"


# ------------------------------------------------------------------ condition classifier
def test_condition_decision_never_forces_a_label():
    classes = ["fresh", "rotten"]
    assert C.decide(np.array([0.95, 0.05]), classes, 0.8, 0.8) == ("fresh", 0.95)
    assert C.decide(np.array([0.1, 0.9]), classes, 0.8, 0.8) == ("possibly_spoiled", 0.9)
    assert C.decide(np.array([0.55, 0.45]), classes, 0.8, 0.8) == ("uncertain", None)
    assert C.decide(np.array([0.2, 0.2, 0.6]), ["Fresh", "Rotten", "Unknown"], 0.5, 0.5) == ("uncertain", None)


def test_class_names_and_reversed_mapping_detection(tmp_path):
    for content, want in ((["fresh", "rotten"], ["fresh", "rotten"]), ({"class_names": ["Rotten", "Fresh"]}, ["Rotten", "Fresh"]),
                          ({"0": "freshapples", "1": "rottenapples"}, ["freshapples", "rottenapples"]),
                          ({"class_to_index": {"rotten": 1, "fresh": 0}}, ["fresh", "rotten"])):
        p = tmp_path / "c.json"
        p.write_text(json.dumps(content), encoding="utf-8")
        assert E.read_class_names(p) == want
    y = np.array(["fresh"] * 50 + ["rotten"] * 50)
    good = np.vstack([np.tile([0.9, 0.1], (50, 1)), np.tile([0.2, 0.8], (50, 1))])
    assert not E.mapping_check(good, ["fresh", "rotten"], y)["likely_reversed"]
    assert E.mapping_check(good, ["rotten", "fresh"], y)["likely_reversed"]  # metadata in the wrong order is caught


def test_thresholds_metrics_and_split_handling():
    rng = np.random.default_rng(0)
    y = np.array(["fresh"] * 200 + ["rotten"] * 200)
    pf = np.concatenate([rng.uniform(0.6, 1.0, 200), rng.uniform(0.0, 0.5, 200)])
    pr = 1 - pf
    th = E.choose_thresholds(pf, pr, y, target_precision=0.9)
    pred = E.decide_all(pf, pr, th["t_fresh"], th["t_rotten"])
    m = E.metrics(y, pred)
    assert m["per_class"]["fresh"]["precision"] >= 0.9 and m["per_class"]["rotten"]["precision"] >= 0.9
    assert set(m["confusion_matrix"]) == {"fresh", "rotten"} and 0 < m["coverage"] <= 1
    assert E.detect_columns(["image_path", "Condition", "split", "food"]) == {"path": "image_path", "condition": "Condition",
                                                                                "split": "split", "food": "food"}
    assert [E.split_role(v) for v in ("val", "Test", "train", "x")] == ["validation", "test", "train", "other"]


def test_leakage_check_counts_identical_images_across_splits():
    a = Image.fromarray((np.random.default_rng(1).uniform(0, 255, (64, 64, 3))).astype(np.uint8))
    b = Image.fromarray((np.random.default_rng(2).uniform(0, 255, (64, 64, 3))).astype(np.uint8))
    hashes = {"train": [E.ahash(a), E.ahash(b)], "test": [E.ahash(a.resize((60, 60)))]}
    assert E.cross_split_duplicates(hashes)["train~test"] == 1


def test_condition_model_is_not_used_without_an_evaluated_matching_config(tmp_path):
    m = C.ConditionModel(tmp_path)
    assert m.assess(photo())["status"] == "not_assessed" and m.status == "not_installed"
    (tmp_path / "condition_classifier.keras").write_bytes(b"model bytes")
    m2 = C.ConditionModel(tmp_path)
    assert not m2.load() and m2.status == "not_evaluated"
    (tmp_path / "condition_config.json").write_text(json.dumps({"model_file": "condition_classifier.keras", "model_sha256": "0" * 64,
                                                                 "class_names": ["fresh", "rotten"], "input_size": 224,
                                                                 "preprocessing": "scale_0_1", "t_fresh": 0.8, "t_rotten": 0.8}))
    m3 = C.ConditionModel(tmp_path)
    assert not m3.load() and m3.status == "model_mismatch"  # config written for a different model file


def test_condition_is_not_assessed_on_poor_photos_or_non_food(tmp_path):
    m = C.ConditionModel(tmp_path)
    assert "quality" in m.assess(photo(), {"level": "poor", "advice": ["Move closer."]})["message"]
    assert m.assess(photo(), {"level": "good"}, is_food=False)["status"] == "not_assessed"


def test_preprocessing_modes():
    img = Image.new("RGB", (10, 10), (255, 0, 0))
    assert C.preprocess_array(img, 4, "scale_0_1").max() == pytest.approx(1.0)
    assert C.preprocess_array(img, 4, "minus1_1").min() == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        C.preprocess_array(img, 4, "bogus")
