"""The 70% identification-confidence rule and freshness assessment after the FINAL food identity
(automatic, OpenAI-resolved, user-confirmed, user-corrected, typed manually).

Recognizer outputs, embeddings, the freshness head and the nutrition CSV are SYNTHETIC fixtures; OpenAI, Google Vision,
USDA and Open Food Facts are mocked. These tests check the decision logic and API contracts, not real-world accuracy:
no real fresh or rotten food photographs are used."""
import io
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.routes import analyze
from app.api.routes import packaged as packaged_route
from app.main import app
from app.ml import freshness as F
from app.services import analysis_store, openai_vision, usda, vision
from app.services import openfoodfacts as off
from tests.test_freshness_nutrition_quality import RealishNutrition, photo, ref  # noqa: F401  (fixture)
from tests.test_freshness_safety_automatic import FRESH_FEATS, MIDDLE_FEATS, ROTTEN_FEATS, HeadRecognizer
from tests.test_packaged_recognition import dataset
from tests.test_recognition_packaged_history_fixes import png
from tests.test_recognition_packaged_history_fixes import oa as openai_result

OA_OFF = {"status": "unavailable", "reason": "not_configured"}


@pytest.fixture
def env(monkeypatch, ref):  # noqa: F811
    state = {"rec": HeadRecognizer(FRESH_FEATS, food="Apple", score=0.95), "oa": OA_OFF}
    app.dependency_overrides[analyze.get_recognizer] = lambda: state["rec"]
    app.dependency_overrides[analyze.get_nutrition] = lambda: RealishNutrition(ref)
    monkeypatch.setattr(vision, "enabled", lambda: False)
    monkeypatch.setattr(openai_vision, "availability", lambda: "ready")

    def identify(img, classes):
        if isinstance(state["oa"], Exception):
            raise state["oa"]
        return state["oa"]
    monkeypatch.setattr(openai_vision, "identify", identify)
    monkeypatch.setattr(analyze, "run_condition", lambda img, q, is_food: {
        "status": "not_assessed", "confidence": None, "model_status": "not_installed", "message": "No condition model."})
    monkeypatch.setattr(usda, "lookup", lambda food, cat, grams=None: {"status": "no_match", "message": f"No USDA match for '{food}'."})
    yield SimpleNamespace(state=state, mp=monkeypatch)
    app.dependency_overrides.clear()


def analyse(c, image=None):
    return c.post("/api/analyze/food", files={"file": ("f.png", image or png("red"), "image/png")}).json()


def confirm(c, food, ref_id=None):
    return c.post("/api/analyze/confirm", json={"food": food, **({"pending_id": ref_id} if ref_id else {})}).json()


def low_score(feats, score=0.5, food="Apple"):
    return HeadRecognizer(feats, food=food, score=score, decision="uncertain", reason="low_confidence")


# ================================================================== A. confidence normalisation and the 70% rule
@pytest.mark.parametrize("value,pct,auto", [
    (0.69, 69.0, False), (0.70, 70.0, True), (0.71, 71.0, True),
    (69, 69.0, False), (70, 70.0, True), (71, 71.0, True),
    (0.6999, 69.99, False), (0.29, 29.0, False), (1, 100.0, True), (0, 0.0, False),
])
def test_confidence_is_normalised_once_and_70_is_accepted(value, pct, auto):
    assert analyze.confidence_percent(value) == pytest.approx(pct)
    assert analyze.has_high_recognition_score(value) is auto


@pytest.mark.parametrize("value", [None, "0.9", True, float("nan"), float("inf"), -0.1, 100.5])
def test_missing_or_invalid_confidence_is_never_treated_as_confident(value):
    assert analyze.confidence_percent(value) is None and analyze.has_high_recognition_score(value) is False


def test_displayed_percentage_never_rounds_up_across_the_threshold():
    assert analyze.display_percent(analyze.confidence_percent(0.69999)) == 69.9
    assert analyze.display_percent(analyze.confidence_percent(0.7)) == 70.0
    assert analyze.display_percent(analyze.confidence_percent(0.29)) == 29.0  # float noise snapped, not floored to 28.9


@pytest.mark.parametrize("score,ok", [(0.69, False), (0.70, True), (0.71, True)])
def test_image_model_low_score_rejection_uses_the_70_percent_rule(env, score, ok):
    env.state["rec"] = low_score(FRESH_FEATS, score=score)
    j = analyse(TestClient(app))
    if ok:
        assert j["success"] and j["requires_confirmation"] is False and j["prediction"]["confidence_percent"] == round(score * 100, 1)
        assert j["acceptance_basis"] == "image_model_score_at_or_above_70"
    else:
        assert j["error_code"] == "LOW_CONFIDENCE" and j["requires_confirmation"] is True and j["confidence_percent"] == 69.0


@pytest.mark.parametrize("score,needs", [(0.69, True), (0.70, False), (0.71, False)])
def test_accepted_single_source_result_carries_the_confirmation_decision(env, score, needs):
    env.state["rec"] = HeadRecognizer(FRESH_FEATS, food="Apple", score=score)  # model's own calibrated verdict: accept
    j = analyse(TestClient(app))
    assert j["success"] and j["requires_confirmation"] is needs


def test_low_score_verified_by_openai_needs_no_confirmation(env):
    env.state["rec"] = HeadRecognizer(FRESH_FEATS, food="Apple", score=0.55)
    env.state["oa"] = openai_result("recognized", "Apple", "Apple", "Fruits")
    j = analyse(TestClient(app))
    assert j["success"] and j["requires_confirmation"] is False and j["acceptance_basis"] == "verified_by_independent_service"


def test_food_outside_the_classes_has_no_invented_score(env):
    env.state["rec"] = HeadRecognizer(FRESH_FEATS, food="Tomato", score=0.3, decision="unsupported_food", reason="far_from_supported_foods")
    env.state["oa"] = openai_result("unsupported_food", "Kiwi", None, "Fruits")
    j = analyse(TestClient(app))
    assert j["success"] and j["prediction"]["confidence"] is None and j["prediction"]["confidence_percent"] is None
    assert j["requires_confirmation"] is False and j["acceptance_basis"] == "openai_identification_without_score"


def test_sources_that_disagree_still_ask_even_at_high_score(env):
    env.state["rec"] = HeadRecognizer(FRESH_FEATS, food="Apple", score=0.95)
    env.state["oa"] = openai_result("recognized", "Tomato", "Tomato", "Vegetables")
    j = analyse(TestClient(app))
    assert j["error_code"] == "LOW_CONFIDENCE" and j["reason"] == "openai_disagreement" and j["requires_confirmation"]


@pytest.mark.parametrize("score,ok", [(0.9, True), (0.7, True), (0.69, False)])
def test_openai_outage_follows_the_70_percent_rule_by_default(env, score, ok):
    env.state["rec"] = HeadRecognizer(FRESH_FEATS, food="Apple", score=score)
    env.state["oa"] = openai_vision.OpenAIVisionError("timeout")
    j = analyse(TestClient(app))
    if ok:
        assert j["success"] and j["requires_confirmation"] is False and j["recognition"]["status"] == "tensorflow_fallback"
        assert j["openai_vision"]["reason"] == "timeout"  # the outage is reported, not hidden
    else:
        assert j["error_code"] == "LOW_CONFIDENCE" and j["reason"] == "openai_unavailable"


def test_repeated_analyses_are_independent(env):
    c = TestClient(app)
    env.state["rec"] = HeadRecognizer(ROTTEN_FEATS, food="Apple", score=0.95)
    first = analyse(c)
    env.state["rec"] = low_score(FRESH_FEATS, score=0.5)
    second = analyse(c)
    assert first["success"] and first["freshness"]["status"] == "possibly_spoiled"
    assert second["error_code"] == "LOW_CONFIDENCE" and second["pending_id"] != first["image_ref"]
    # each reference stays bound to its own photo
    assert confirm(c, "Apple", second["pending_id"])["freshness"]["status"] == "fresh"
    assert confirm(c, "Apple", first["image_ref"])["freshness"]["status"] == "possibly_spoiled"


# ================================================================== B. freshness after the final identity
@pytest.mark.parametrize("feats,status", [(FRESH_FEATS, "fresh"), (ROTTEN_FEATS, "possibly_spoiled")])
def test_manually_typed_apple_is_assessed_on_the_uploaded_photo(env, feats, status):
    env.state["rec"] = low_score(feats, score=0.4)
    c = TestClient(app)
    low = analyse(c)
    j = confirm(c, "apple", low["pending_id"])  # typed in the picker, lower case
    assert j["identification"]["food"] == "Apple" and j["identification"]["source"] == "user_selected"
    assert j["freshness"]["status"] == status and "selected manually" not in j["freshness"]["message"]


def test_correcting_an_accepted_result_reassesses_the_same_photo_for_the_new_food(env):
    env.state["rec"] = HeadRecognizer(ROTTEN_FEATS, food="Banana", score=0.95)
    c = TestClient(app)
    first = analyse(c)
    assert first["prediction"]["food"] == "Banana" and first["image_ref"]
    fixed = confirm(c, "Apple", first["image_ref"])
    assert fixed["identification"]["food"] == "Apple" and fixed["freshness"]["status"] == "possibly_spoiled"
    assert fixed["nutrition"]["source_fdc_id"] == 171688  # nutrition follows the corrected identity
    assert fixed["safety_alert"]["level"] == "danger"


def test_borderline_photo_stays_borderline_after_confirmation(env):
    env.state["rec"] = low_score(MIDDLE_FEATS)
    c = TestClient(app)
    j = confirm(c, "Apple", analyse(c)["pending_id"])
    assert j["freshness"]["status"] == "uncertain" and j["safety_alert"]["level"] == "caution"


def test_food_the_model_was_not_trained_for_is_reported_not_guessed(env):
    env.state["rec"] = low_score(ROTTEN_FEATS)
    c = TestClient(app)
    ref_id = analyse(c)["pending_id"]
    tomato = confirm(c, "Tomato", ref_id)  # one of the classes, but not in the freshness head's supported foods
    kiwi = confirm(c, "Kiwi", ref_id)  # typed, outside the classes
    for j, name in ((tomato, "Tomato"), (kiwi, "Kiwi")):
        assert j["freshness"]["status"] == "not_assessed" and f"not supported for {name}" in j["freshness"]["message"]
        assert j["safety_alert"] is None


def test_without_a_photo_reference_the_reason_is_explicit(env):
    c = TestClient(app)
    assert "not linked to an analysed photo" in confirm(c, "Apple")["freshness"]["message"]
    assert "no longer held on the server" in confirm(c, "Apple", "expired-or-unknown-id")["freshness"]["message"]


def test_a_finished_result_id_cannot_be_used_as_a_photo(env):
    c = TestClient(app)
    env.state["rec"] = HeadRecognizer(ROTTEN_FEATS, food="Apple", score=0.95)
    done = analyse(c)
    j = confirm(c, "Apple", done["analysis_id"])  # a stored RESULT, not a photo reference
    assert j["freshness"]["status"] == "not_assessed"


def test_missing_freshness_model_is_reported_explicitly(env):
    rec = env.state["rec"] = HeadRecognizer(ROTTEN_FEATS, food="Apple", score=0.95)
    rec.freshness = F.FreshnessHead(model_dir=None)  # nothing installed
    j = analyse(TestClient(app))
    assert j["freshness"]["status"] == "not_assessed" and j["freshness"]["model_status"] == "not_installed"
    assert "not installed" in j["freshness"]["message"] and j["safety_alert"] is None


def test_mismatched_or_corrupt_freshness_model_is_disabled_with_its_reason(tmp_path):
    (tmp_path / "freshness_head.npz").write_bytes(b"not a numpy file")
    (tmp_path / "freshness_config.json").write_text('{"food_model_sha256": "abc"}', encoding="utf-8")
    h = F.FreshnessHead(tmp_path)
    assert h.load("different") is False and h.status == "model_mismatch"
    assert "different food-recognition model" in h.assess(ROTTEN_FEATS, "Apple", True)["message"]
    h2 = F.FreshnessHead(tmp_path)
    assert h2.load("abc") is False and h2.status == "error"
    assert "could not be loaded" in h2.assess(ROTTEN_FEATS, "Apple", True)["message"]


@pytest.mark.parametrize("path", ["analyse", "confirm"])
def test_inference_failure_is_an_explicit_error_never_fresh(env, path):
    rec = env.state["rec"] = HeadRecognizer(FRESH_FEATS, food="Apple", score=0.95 if path == "analyse" else 0.4,
                                            decision="accept" if path == "analyse" else "uncertain", reason=None if path == "analyse" else "low_confidence")

    def boom(features, food):
        raise RuntimeError("inference crashed")
    rec.assess_freshness = boom
    c = TestClient(app)
    j = analyse(c) if path == "analyse" else confirm(c, "Apple", analyse(c)["pending_id"])
    assert j["freshness"]["status"] == "not_assessed" and j["freshness"]["model_status"] == "error"
    assert "failed" in j["freshness"]["message"]


@pytest.mark.real_quality  # the conftest stubs quality assessment otherwise, which would skip the enhancement retry
def test_freshness_uses_the_original_photo_not_the_enhanced_copy(env):
    seen = {}

    class DarkRecognizer(HeadRecognizer):
        def analyze_image(self, img):
            mean = float(np.asarray(img.convert("L")).mean())
            first = "orig" not in seen
            seen.setdefault("orig", mean) if first else seen.setdefault("enhanced", mean)
            self.feats = ROTTEN_FEATS if first else FRESH_FEATS  # spoilage visible only in the original photo
            self.decision, self.reason = ("uncertain", "low_confidence") if first else ("accept", None)
            return super().analyze_image(img)

    env.state["rec"] = DarkRecognizer(ROTTEN_FEATS, food="Apple", score=0.6)
    conditions = []
    env.mp.setattr(analyze, "run_condition", lambda img, q, is_food: conditions.append(float(np.asarray(img.convert("L")).mean())) or {
        "status": "not_assessed", "confidence": None, "model_status": "not_installed", "message": "x"})
    buf = io.BytesIO()
    photo(bright=0.2).save(buf, "PNG")
    j = analyse(TestClient(app), buf.getvalue())
    assert seen["enhanced"] > seen["orig"] and j["enhancement"]["used"] == "enhanced"
    assert j["freshness"]["status"] == "possibly_spoiled"  # judged on the original, not the brightened copy
    assert conditions == [pytest.approx(seen["orig"])]  # condition model also received the original photo


# ================================================================== C/D. safety and nutrition on the confirmation path
def test_rotten_confirmation_never_encourages_eating(env):
    env.state["rec"] = low_score(ROTTEN_FEATS)
    c = TestClient(app)
    j = confirm(c, "Apple", analyse(c)["pending_id"])
    texts = " ".join(p["text"] for p in j["precautions"]).lower()
    assert "do not eat this food" in texts and "just before eating" not in texts and "cut away bruised" not in texts
    assert any("not lowered or changed" in n for n in j["notes"])


def test_fresh_result_is_not_called_safe(env):
    j = analyse(TestClient(app))
    assert j["freshness"]["status"] == "fresh" and j["safety_alert"] is None
    assert any("does not prove the food is safe" in p["text"] for p in j["precautions"])


def test_nutrition_is_per_scan_and_missing_values_stay_missing(env):
    c = TestClient(app)
    apple = analyse(c)
    env.state["rec"] = HeadRecognizer(FRESH_FEATS, food="Banana", score=0.95)
    banana = analyse(c)
    assert apple["nutrition"]["source_fdc_id"] == 171688 and banana["nutrition"]["source_fdc_id"] == 173944
    env.state["rec"] = HeadRecognizer(FRESH_FEATS, food="Tomato", score=0.95)  # no record in the fixture CSV
    tomato = analyse(c)
    assert tomato["nutrition"] is None and tomato["nutrition_error"]


# ================================================================== E. packaged: barcode / pack-text mismatch
def test_barcode_record_contradicted_by_the_pack_text_is_flagged(monkeypatch, tmp_path):
    app.dependency_overrides[packaged_route.get_packaged_data] = lambda: dataset(tmp_path, without_maggi=True)
    monkeypatch.setattr(packaged_route, "run_ocr", lambda img: {"text": "Energy 500 kcal per 100 g", "confidence": 80.0,
                                                                "word_count": 6, "rotation": 0, "quality": "good"})
    monkeypatch.setattr(packaged_route, "run_front_ocr", lambda img: {"text": "ZORBO Millet Puffs", "prominent": ["ZORBO", "Millet", "Puffs"]})
    monkeypatch.setattr(packaged_route, "run_barcode", lambda img: {"status": "found", "code": "8901058851380", "format": "EAN-13"})
    monkeypatch.setattr(packaged_route, "run_package_reading", lambda f, b: {"status": "unavailable", "reason": "not_configured"})
    monkeypatch.setattr(off, "enabled", lambda: True)
    monkeypatch.setattr(off, "by_barcode", lambda code: {"status": "found", "barcode": code, "product": {
        "code": code, "name": "Choco Wafers", "brand": "Elsewhere", "nutrition_per_100g": {"energy_kcal": 530.0}, "allergens": [],
        "traces": [], "additive_codes": [], "ingredients_text": None, "url": None, "source": "Open Food Facts (crowd-sourced)",
        "quantity": None, "serving_size": None}})
    try:
        j = TestClient(app).post("/api/analyze/packaged", files={"front": ("f.png", png("blue"), "image/png"),
                                                                 "back": ("b.png", png("white"), "image/png")}).json()
    finally:
        app.dependency_overrides.clear()
    assert j["external"]["verified_against_label"] is False and "not found in the text read from the pack" in j["external"]["message"]
    rows = {r["key"]: r for r in j["label_nutrition"]["rows"]}
    assert rows["energy_kcal"]["value"] == 500 and "total_sugars_g" not in rows  # label values kept; missing fields not filled


def test_photo_reference_store_keeps_kinds_separate():
    pid = analysis_store.put("pending", {"features": None})
    assert analyze.photo_for(pid) is not None and analyze.photo_for(analysis_store.put("fresh", {})) is None


# ================================================================== image quality: plain backgrounds are not "blur"
def food_on_white(blur: float = 0.0):
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.new("RGB", (1200, 900), (222, 222, 218))  # plain light surface, as in many real food photos
    tex = Image.fromarray(np.random.default_rng(3).integers(60, 200, (260, 260, 3)).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))
    mask = Image.new("L", (260, 260), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 259, 259], fill=255)
    img.paste(tex, (470, 320), mask)  # a detailed item covering ~5% of the frame
    return img.filter(ImageFilter.GaussianBlur(blur)) if blur else img


@pytest.mark.real_quality  # conftest stubs the assessment otherwise
def test_sharp_food_on_a_plain_background_is_not_rated_blurred():
    from app.ml import image_quality as Q
    sharp, blurred = Q.assess(food_on_white()), Q.assess(food_on_white(blur=6))
    assert not {"blurry", "slightly_blurry"} & set(sharp["issues"]) and sharp["level"] == "good"
    assert "blurry" in blurred["issues"] and blurred["level"] == "poor"  # real blur is still caught
