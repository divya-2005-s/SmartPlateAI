"""POST /api/analyze/food and GET /api/models/status."""
from __future__ import annotations

import logging
import math
import os
import threading
import time

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import User, optional_user
from app.api.limits import analysis_guard, limit
from app.core.config import get_settings
from app.data.class_references import CATEGORY_VARIANTS, GENERIC_CAVEATS, category_for_name, is_category
from app.ml import image_quality
from app.ml.condition import ConditionModel
from app.ml.freshness import annotate as annotate_freshness
from app.ml.recognizer import MSG_LOW_CONF, MSG_NON_FOOD, MSG_UNSUPPORTED, FoodRecognizer, ImageError, decode_upload
from app.services import analysis_store, food_category, gemini_vision, history, openai_vision, usage_limits, usda, vision
from app.services.nutrition import NutritionReference
from app.services.precautions import for_food, safety_alert

log = logging.getLogger("smartplate.api")
MSG_VISION = ("The image model and Google Vision do not agree on what this food is. Please choose the correct food if it is "
              "listed, or try a clearer photo.")
MSG_VISION_NO_FOOD = ("Google Vision did not detect food in this photo, so the model's guess was not accepted. Choose the food if it is listed, "
                      "or upload a clear photo of food.")
MSG_DISAGREE = ("This photo does not clearly match one food: the model's checks point to different foods. "
                "It may be a food SmartPlateAI does not support. Choose the correct food if it is listed, or try a clearer photo.")
MSG_OPENAI_DISAGREE = ("OpenAI and the food model identify different foods. Please confirm the correct supported food before nutrition is shown.")
MSG_OPENAI_NO_FOOD = ("OpenAI could not verify that this photo contains recognizable food. Please confirm the food or upload a clearer photo.")
MSG_OPENAI_UNCERTAIN = ("OpenAI could not identify the food clearly. Please confirm the food or upload a clearer photo.")
MSG_OPENAI_UNSUPPORTED = ("OpenAI identified food outside SmartPlateAI's supported classes. No nutrition is shown until you choose a supported food.")
MSG_OPENAI_UNAVAILABLE = ("OpenAI could not check this photo ({reason}), so the food model's answer has not been independently "
                          "verified. Please confirm the food before using nutrition.")
MSG_QUOTA = ("OpenAI could not be used because the OpenAI account has no remaining credit, so foods outside the 24 supported "
             "classes cannot be identified until credit is added.")
OPENAI_OFF = ("disabled", "not_configured", "login_required")  # deliberately not used: the image model alone answers, clearly labelled
# Anonymous visitors on a deployment with PAID_PROVIDERS_REQUIRE_LOGIN: the image model alone, exactly as with providers off.
LOGIN_REQUIRED = {"status": "unavailable", "reason": "login_required", "provider": "OpenAI Vision"}
MSG_LOGIN_FOR_AI = ("AI verification (OpenAI / Google Gemini / Google Vision) is available to signed-in users; this result uses the "
                    "SmartPlateAI image model alone, which knows only 24 foods.")
MSG_DAILY_LIMIT = ("The server's daily limit for AI verification has been reached, so this result uses the SmartPlateAI image model "
                   "alone, which knows only 24 foods. AI verification is available again tomorrow (UTC).")
AUTO_ACCEPT_SCORE_THRESHOLD = 0.7
router = APIRouter(prefix="/api", tags=["analysis"])
MAX_MB = float(os.environ.get("MAX_UPLOAD_MB", "8"))
MAX_BYTES = int(MAX_MB * 1024 * 1024)

_recognizer: FoodRecognizer | None = None
_nutrition: NutritionReference | None = None
_condition: ConditionModel | None = None
_singleton_lock = threading.Lock()


def get_recognizer() -> FoodRecognizer:
    global _recognizer
    with _singleton_lock:
        if _recognizer is None:
            _recognizer = FoodRecognizer()
    return _recognizer


def get_nutrition() -> NutritionReference:
    global _nutrition
    with _singleton_lock:
        if _nutrition is None:
            _nutrition = NutritionReference()
    return _nutrition


def get_condition() -> ConditionModel:
    global _condition
    with _singleton_lock:
        if _condition is None:
            _condition = ConditionModel()
    return _condition


def run_condition(img, quality: dict, is_food: bool) -> dict:
    try:
        return get_condition().assess(img, quality, is_food)
    except Exception:  # noqa: BLE001
        log.exception("condition model assessment failed")
        return {"status": "not_assessed", "confidence": None, "model": "condition_classifier",
                "model_status": "error", "message": "Freshness could not be assessed because the condition model failed."}


MSG_PACKAGED_PHOTO = ("This looks like a packaged product, and no food is visible in the photo to identify. Its nutrition is printed "
                      "on the pack: use Scan packaged food to read the label or barcode. If this is not a food product, please "
                      "upload a photo of food.")
MSG_WEAK_EVIDENCE = ("The image model named a food, but a second check found little visual evidence of food in this photo (it may be "
                     "a package or another object). Please confirm the food, or use Scan packaged food for a packaged product.")
MSG_POOR_QUALITY = ("The photo quality is too low for a reliable result. {advice} You can also confirm the food yourself below.")


def condition_note(freshness: dict, food: str | None) -> str | None:
    if freshness.get("status") == "possibly_spoiled":
        return (f"The nutrition shown is the reference profile for {food or 'this food'}. Spoilage changes composition, but this "
                "app cannot measure it, so the values are not lowered or changed. Spoiled food should not be eaten.")
    return None


def error(code: str, message: str, status: int, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"success": False, "error_code": code, "message": message, **extra})


def lacks_food_signal(rec, result: dict) -> bool:
    """The image model's own "does not look like food" evidence: ImageNet food mass below the calibrated floor that the
    non-food gate already uses (Thresholds.food_mass_low). False when rejection is uncalibrated or the signal is missing."""
    th = getattr(rec, "thresholds", None)
    mass = (result.get("signals") or {}).get("imagenet_food_mass")
    return th is not None and isinstance(mass, (int, float)) and math.isfinite(mass) and mass < th.food_mass_low


def is_valid_recognition_score(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


AUTO_ACCEPT_PERCENT = AUTO_ACCEPT_SCORE_THRESHOLD * 100  # 70.0


def confidence_percent(value: object) -> float | None:
    """Image-identification confidence as a percentage, or None if missing/invalid.
    0..1 is a fraction (0.7 -> 70.0); 1 < value <= 100 is already a percentage (70 -> 70.0, never scaled twice).
    Snapped to 6 decimals so float noise cannot move a value across the threshold (0.29 * 100 = 28.999999999999996)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 100:
        return None
    return round(value * 100 if value <= 1 else float(value), 6)


def display_percent(pct: float | None) -> float | None:
    """Rounded DOWN to one decimal, so a displayed '70.0%' is always a value that passed the >= 70% rule."""
    return None if pct is None else math.floor(round(pct * 10, 6)) / 10


def has_high_recognition_score(value: object) -> bool:
    """The single auto-accept rule: identification confidence >= 70% (exactly 70% is accepted)."""
    pct = confidence_percent(value)
    return pct is not None and pct >= AUTO_ACCEPT_PERCENT


class ConfirmFoodRequest(BaseModel):
    food: str = Field(min_length=1, max_length=120)
    serving_grams: float | None = Field(default=None, ge=1, le=2000)
    # The analysed photo this choice belongs to (`pending_id` / `image_ref` of the analysis response). With it, freshness is
    # assessed on that photo for the chosen food, and a food outside the 24 classes suggested for the photo can be confirmed.
    pending_id: str | None = Field(default=None, max_length=64)
    # For a category food (Sandwich, Burger, ...): true = the user explicitly accepts the generic, clearly labelled reference
    # record instead of choosing a specific type. Without it, choosing the category confirms the identity only.
    accept_generic: bool = False


@router.get("/models/status")
def models_status(rec: FoodRecognizer = Depends(get_recognizer)) -> dict:
    rec.load()
    nut = get_nutrition()
    nut_ok = nut.load()
    return {"food_classifier": rec.info(), "condition_classifier": get_condition().info(),
            "nutrition_reference": {"loaded": nut_ok, "error": nut.error,
                                    "foods_with_conflicting_rows": nut.conflicts if nut_ok else None}}


@router.post("/analyze/food")
def analyze_food(file: UploadFile = File(...), serving_grams: float | None = Form(None),
                 rec: FoodRecognizer = Depends(get_recognizer), nutrition: NutritionReference = Depends(get_nutrition),
                 user: User | None = Depends(optional_user), idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
                 _guard: None = Depends(analysis_guard)):
    if serving_grams is not None and not (1 <= serving_grams <= 2000):
        return error("INVALID_SERVING", "Serving size must be between 1 and 2000 grams.", 422)
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        return error("FILE_TOO_LARGE", f"The image is larger than {MAX_MB:g} MB. Please upload a smaller photo.", 413)
    if not data:
        return error("INVALID_IMAGE", "The uploaded file is empty. Please choose a photo and try again.", 400)
    if not rec.load():
        return error("MODEL_UNAVAILABLE", rec.status_message, 503)
    t0 = time.time()
    enhancement = {"applied": False, "used": "original"}
    try:
        img = decode_upload(data)
        quality = image_quality.assess(img)
        result = rec.analyze_image(img)
        # Embedding of the ORIGINAL photo: freshness is always judged on what was uploaded, never on the
        # brightness/contrast-corrected copy (enhancement may help identification but can alter how spoilage looks).
        features = result.pop("features", None)
        if quality["enhanceable"] and result["decision"] != "accept":
            enhanced = image_quality.enhance(img)
            enhanced_result = rec.analyze_image(enhanced)
            enhanced_result.pop("features", None)
            chosen, which = image_quality.choose(result, enhanced_result)
            enhancement = {"applied": True, "used": which, "for": quality["issues"]}
            if which == "enhanced":
                result = chosen
    except ImageError as exc:
        return error(exc.code, exc.message, exc.status)
    except Exception:  # noqa: BLE001
        log.exception("analysis failed")
        return error("INTERNAL_ERROR", "Something went wrong while analysing the image. Please try again.", 500)
    log.info("analyze decision=%s bytes=%d ms=%d", result["decision"], len(data), (time.time() - t0) * 1000)

    decision = result["decision"]
    model_food = result["top_k"][0]["food"] if result.get("top_k") else None
    paid = usage_limits.paid_allowed(user)  # anonymous on a public deployment: no paid provider is called
    oa = run_openai_vision(img, rec.class_names) if paid else dict(LOGIN_REQUIRED)
    oa_food = oa.get("supported_food") if oa.get("status") == "recognized" else None
    # Two independent checks agree there is no food: the vision provider says the photo contains none, and the image
    # model's own food signal is below its calibrated floor. Either one alone stays "uncertain" (ambiguous photo).
    if decision in ("accept", "uncertain") and oa.get("status") == "no_food" and lacks_food_signal(rec, result):
        decision, result["reason"] = "non_food", "no_food_confirmed"
    if decision == "non_food":
        if oa_food:
            decision, result["reason"] = "uncertain", "openai_disagreement"
        elif oa.get("status") == "unsupported_food":
            decision = "unsupported_food"
        elif oa.get("status") == "uncertain":
            decision, result["reason"] = "uncertain", "openai_uncertain"
    elif decision == "unsupported_food":
        if oa_food or oa.get("status") in ("no_food", "uncertain"):
            reason = "openai_disagreement" if oa_food else "openai_no_food" if oa.get("status") == "no_food" else "openai_uncertain"
            decision, result["reason"] = "uncertain", reason
    elif decision == "accept":
        if oa_food and model_food and oa_food != model_food:
            decision, result["reason"] = "uncertain", "openai_disagreement"
        elif oa.get("status") == "unsupported_food":
            decision, result["reason"] = "uncertain", "openai_unsupported_food"
        elif oa.get("status") == "no_food":
            decision, result["reason"] = "uncertain", "openai_no_food"
        elif oa.get("status") == "uncertain":
            decision, result["reason"] = "uncertain", "openai_uncertain"
    elif decision == "uncertain":
        if oa_food and model_food and oa_food != model_food:
            result["reason"] = "openai_disagreement"
        elif oa.get("status") == "unsupported_food":
            result["reason"] = "openai_unsupported_food"
        elif oa.get("status") == "no_food":
            result["reason"] = "openai_no_food"
        elif oa.get("status") == "uncertain":
            result["reason"] = "openai_uncertain"
        elif oa_food and oa_food == model_food and result.get("reason") in ("low_confidence", "classifier_disagreement"):
            # An independent identification of the same food resolves the image model's own hesitation (a low score, or
            # its softmax and feature-space checks disagreeing), so the result is shown without asking the user.
            decision, result["reason"] = "accept", None

    # A food outside the 24 classes named by OpenAI is accepted as a general identification when the image model does
    # not claim a supported class for it (the model itself says "not one of mine", "not food" or is not confident).
    general_name = oa.get("food_name") if oa.get("status") == "unsupported_food" else None
    general_category = food_category.resolve(general_name, oa.get("category")) if general_name else None
    tf_decision = result["decision"]  # the image model's own verdict, before any second opinion
    # Also when the image model "accepted" a class with a score below 70%: that is not enough evidence for the class
    # (47.8% of such test images were wrong), while OpenAI clearly named a food the model was never trained on.
    # At >= 70% the two sources genuinely disagree, so the user is asked (OpenAI's suggestion is offered first).
    weak_accept = tf_decision == "accept" and not has_high_recognition_score(result.get("confidence"))
    if general_name and (tf_decision in ("non_food", "unsupported_food", "uncertain") or weak_accept):
        decision, result["reason"] = "general", None

    predicted_for_vision = general_name if decision == "general" else (model_food if decision in ("accept", "uncertain") else None)
    vis = run_vision(img, predicted_for_vision, rec.class_names) if paid and decision in ("accept", "uncertain", "unsupported_food", "general") else None
    if decision in ("accept", "general") and vis and vis.get("status") in ("conflicts", "no_food"):
        decision = "uncertain"
        result["reason"] = "vision_disagreement" if vis["status"] == "conflicts" else "vision_no_food"
    openai_failed = oa.get("status") == "unavailable" and oa.get("reason") not in OPENAI_OFF
    if decision == "accept" and openai_failed and not (vis and vis.get("status") == "agrees") \
            and openai_outage_needs_confirmation(oa.get("reason"), result.get("confidence")):
        decision, result["reason"] = "uncertain", "openai_unavailable"
    # The 70% rule. The image model's top-class score is the identification confidence exposed by this API (a softmax
    # score, not a calibrated probability). At >= 70% the model's own low-score/margin rejection is overridden.
    # Disagreements are not confidence questions and still ask the user: the model's softmax and feature-space checks
    # naming different foods (classifier_disagreement), another source naming a different food, "no food" verdicts and
    # poor photos. (OpenAI naming the same food resolves classifier_disagreement above.)
    if decision == "uncertain" and (result.get("reason") or "low_confidence") == "low_confidence" \
            and has_high_recognition_score(result.get("confidence")):
        decision, result["reason"] = "accept", None
    # Evidence checks that apply only when nothing independent identified the food (no provider answer, no Vision agreement).
    # Both use existing signals: ImageNet's top class and the calibrated food-mass floor; no new threshold.
    provider_answered = oa.get("status") in ("recognized", "unsupported_food", "no_food")
    verified = (oa_food is not None and oa_food == model_food) or bool(vis and vis.get("status") == "agrees")
    if result.get("packaged_product") and not provider_answered and decision in ("accept", "uncertain", "non_food"):
        # A package with no visible food: neither "this is food X" nor "this is not food". Its nutrition is on the label.
        decision, result["reason"] = "packaged_product", "package_without_food_evidence"
    elif decision == "accept" and not verified and lacks_food_signal(rec, result):
        # Named confidently by the 24-class model, but the independent ImageNet check sees no food (a chips packet called
        # "Fries", a phone called "Donut"): ask instead of showing that food's nutrition. The score is not a probability.
        decision, result["reason"] = "uncertain", "weak_food_evidence"
    poor = quality["level"] == "poor"
    if poor and decision in ("accept", "general"):
        decision, result["reason"] = "uncertain", "poor_image_quality"
    # Nor can a poor photo support "no food" (a dark or blurred meal shows no food to either check): ask for a better
    # photo instead, without offering the model's guesses for an image it judged to contain no food.
    unreadable = poor and decision == "non_food"
    if unreadable:
        decision, result["reason"] = "uncertain", "poor_image_quality"
    condition = run_condition(img, quality, is_food=decision not in ("non_food", "packaged_product"))  # food-independent, on the original photo
    condition_ready = condition.get("model_status") == "ready"
    extras = {"image_quality": quality, "enhancement": enhancement}
    general = {"food": general_name, "category": general_category, "source": provider_name(oa),
               "note": "Not one of the 24 foods the image model was trained on."} if general_name else None
    # Everything needed to assess freshness of THIS photo later, for whichever food is finally confirmed or corrected.
    # The embedding is computed from the original photo by the same model the freshness head was trained on, so running
    # the head on it later is the same inference as running it on the photo now. Expires with the analysis store.
    photo = {"features": features, "condition": condition if condition_ready else None, "poor": poor,
             "fallback": result.get("freshness"), "choices": [c["food"] for c in result.get("top_k", [])],
             "general": general, **extras}
    image_ref = analysis_store.put("pending", photo)
    final_food = model_food if decision == "accept" else general_name if decision == "general" else None
    if final_food:
        freshness = assess_photo_freshness(rec, photo, final_food)
    else:  # identity not settled yet: only a food-independent result can be shown now
        freshness = annotate_freshness(condition if condition_ready and not poor else (
            {"status": "not_assessed", "confidence": None, "message": "Freshness was not assessed because the photo quality is too low."}
            if poor else result.get("freshness") or {"status": "not_assessed", "confidence": None,
                                                     "message": "Freshness is assessed once the food is identified."}))
    recognition = recognition_summary(decision, oa, oa_food == model_food and model_food is not None, vis)
    if decision == "general":
        return general_identification(general_name, general_category, oa, vis, serving_grams, user, idempotency_key,
                                      freshness=freshness, extras=extras, image_ref=image_ref, nutrition_ref=nutrition,
                                      class_names=rec.class_names)
    if decision == "packaged_product":
        return error("PACKAGED_PRODUCT", MSG_PACKAGED_PHOTO, 422, reason=result.get("reason"), recognition=recognition,
                     openai_vision=oa, suggest_packaged_scan=True, **extras)
    if decision == "non_food":
        return error("NON_FOOD_IMAGE", MSG_NON_FOOD, 422, reason=result.get("reason"), recognition=recognition, openai_vision=oa,
                     **extras)
    if decision == "unsupported_food":
        return error("UNSUPPORTED_FOOD", MSG_UNSUPPORTED, 422, reason=result.get("reason"), vision=vis,
                     recognition=recognition, openai_vision=oa, freshness=freshness, image_ref=image_ref, pending_id=image_ref,
                     **extras)
    if decision == "uncertain":
        reason = result.get("reason") or "low_confidence"
        pending_id = image_ref
        message = MSG_POOR_QUALITY.format(advice=" ".join(quality["advice"][:1])) if reason == "poor_image_quality" else \
            {"classifier_disagreement": MSG_DISAGREE, "vision_disagreement": MSG_VISION, "vision_no_food": MSG_VISION_NO_FOOD,
             "openai_disagreement": for_provider(MSG_OPENAI_DISAGREE, oa), "openai_no_food": for_provider(MSG_OPENAI_NO_FOOD, oa),
             "openai_uncertain": for_provider(MSG_OPENAI_UNCERTAIN, oa),
             "openai_unavailable": (MSG_QUOTA + " Please confirm the food." if oa.get("reason") == "quota_exhausted" else
                                    MSG_OPENAI_UNAVAILABLE.format(reason=str(oa.get("reason", "unavailable")).replace("_", " "))),
             "openai_unsupported_food": for_provider(MSG_OPENAI_UNSUPPORTED, oa),
             "weak_food_evidence": MSG_WEAK_EVIDENCE}.get(reason, MSG_LOW_CONF)
        confidence = result.get("confidence")
        margin = result.get("margin")
        return error(
            "LOW_CONFIDENCE",
            message,
            422,
            general_candidate=general,
            pending_id=pending_id,
            image_ref=image_ref,
            reason=reason,
            candidates=[] if unreadable else result["top_k"],
            **({"confidence": round(confidence, 4),
                "confidence_percent": display_percent(confidence_percent(confidence))} if is_valid_recognition_score(confidence) else {}),
            **({"margin": round(margin, 4)} if is_valid_recognition_score(margin) else {}),
            requires_confirmation=True,
            vision=vis,
            recognition=recognition,
            openai_vision=oa,
            freshness=freshness,
            safety_alert=safety_alert(freshness),
            **extras,
        )

    top = result["top_k"][0]
    nut = nutrition.lookup(top["food"], serving_grams)
    choice = specific_type_choice(top["food"], nut, oa)
    if choice:  # a category ("Sandwich"): its one generic record is not this food's nutrition until the user says so
        nut = None
    warnings = [] if result["calibrated"] else ["non_food_rejection_not_calibrated"]
    agrees = oa_food == top["food"]
    confidence = result.get("confidence")
    margin = result.get("margin")
    independent = agrees or bool(vis and vis.get("status") == "agrees")
    high = has_high_recognition_score(confidence)
    body = {"success": True,
            "image_ref": image_ref,
            "prediction": {"food": top["food"], "class_id": top["class_id"],
                           "confidence": round(confidence, 4) if is_valid_recognition_score(confidence) else None,
                           "confidence_percent": display_percent(confidence_percent(confidence)) if is_valid_recognition_score(confidence) else None,
                           "margin": round(margin, 4) if is_valid_recognition_score(margin) else None, "top_k": result["top_k"]},
            # Single source of truth for the confirmation step: below 70% with no independent verification -> ask.
            "requires_confirmation": not high and not independent,
            "acceptance_basis": "image_model_score_at_or_above_70" if high else
                                "verified_by_independent_service" if independent else "needs_user_confirmation",
            "identification": {"food": top["food"], "category": food_category.resolve(top["food"], oa.get("category") if agrees else None),
                               "specificity": "category" if choice else "specific", "specific_type": None if choice else top["food"],
                               "source": "image_model_and_openai" if agrees else "image_model", "supported_class": top["food"],
                               "provider": provider_name(oa) if agrees else None,
                               "verified_by": ["SmartPlateAI image model"] + ([provider_name(oa)] if agrees else []) +
                                              (["Google Vision"] if vis and vis.get("status") == "agrees" else [])},
            "freshness": freshness,
            "vision": vis,
            "recognition": recognition,
            "openai_vision": oa,
            "nutrition": nut,
            "nutrition_error": choice["message"] if choice else None if nut else (nutrition.error or "No nutrition reference record for this food."),
            "nutrition_choice": choice,
            "safety_alert": safety_alert(freshness, top["food"]),
            "precautions": for_food(top["food"], freshness),
            "notes": ["Confidence is the model's score, not a guarantee that the label is correct.",
                      "SmartPlateAI recognises 24 food types only. A food outside this list can still be mistaken for a similar one; "
                      "use 'Not correct?' to fix it.",
                      "Food identity and freshness are separate estimates with separate confidence.",
                      *filter(None, [condition_note(freshness, top["food"])])],
            "warnings": warnings, **extras}
    body["analysis_id"] = analysis_store.put("fresh", dict(body))
    body["history"] = history.autosave(user, "fresh", dict(body), body["analysis_id"], history.clean_key(idempotency_key))
    return body


def generic_alternative(food: str, nut: dict | None, nut_err: str | None, nutrition, class_names) -> tuple[dict | None, str | None]:
    """A specific dish without its own USDA record ('Paneer sandwich'): offer, never apply, the generic record of its category."""
    parent = category_for_name(food)
    if nut is not None or parent is None or parent not in list(class_names or []) or nutrition is None:
        return None, nut_err
    generic = nutrition.lookup(parent)
    if not generic:
        return None, nut_err
    alt = {"food": parent, "description": generic.get("matched_description"), "fdc_id": generic.get("source_fdc_id"),
           "caveat": GENERIC_CAVEATS.get(parent)}
    return alt, (f"{nut_err or 'No verified nutrition record matches this food.'} You can instead use the generic {parent.lower()} "
                 f"reference ({alt['description'] or 'one USDA record'}); it is not specific to {food.lower()}.")


def specific_type_choice(food: str, generic: dict | None, oa: dict | None = None) -> dict | None:
    """For a category class (Sandwich, Burger, ...): the choice the user must make before nutrition is shown. None otherwise.
    The model recognised the category only; the generic record is offered, described exactly, but never applied silently."""
    if not is_category(food):
        return None
    named = (oa or {}).get("named_as") or (oa or {}).get("food_name")
    suggested = named if named and named.casefold() != food.casefold() and category_for_name(named) == food else None
    options = ([suggested] if suggested else []) + [v for v in CATEGORY_VARIANTS[food] if not suggested or v.casefold() != suggested.casefold()]
    ref = None
    if generic:
        ref = {"food": food, "fdc_id": generic.get("source_fdc_id"), "description": generic.get("matched_description"),
               "data_type": generic.get("data_type"), "source_url": generic.get("source_url"), "caveat": GENERIC_CAVEATS.get(food)}
    what = f"USDA record: {ref['description']}" if ref and ref.get("description") else "a single USDA record"
    return {"category": food, "specific_type": None, "suggested": suggested, "options": options, "generic_reference": ref,
            "message": (f"The image model recognised a {food.lower()}, but it cannot tell which kind (filling or topping), and nutrition "
                        f"differs a lot between kinds. Choose the specific type, or use the generic {food.lower()} reference ({what}), "
                        "which is labelled as generic.")}


def openai_outage_needs_confirmation(reason: str | None, confidence: object) -> bool:
    """OpenAI is configured but failed, and Google Vision did not agree. OPENAI_FAILURE_POLICY:
    'threshold' (default): the 70% rule decides, as for any image-model result without a second opinion;
    'confirm': always ask (stricter); 'fallback': ask only when rate-limited (the original behaviour)."""
    policy = get_settings().openai_failure_policy
    if policy == "confirm":
        return True
    if policy == "fallback":
        return reason == "rate_limited"
    return not has_high_recognition_score(confidence)


NOT_ASSESSED = {"status": "not_assessed", "confidence": None}
MSG_NO_PHOTO = ("Freshness was not assessed because this food choice is not linked to an analysed photo. "
                "Analyse the photo first, then choose or correct the food.")
MSG_PHOTO_EXPIRED = ("Freshness was not assessed because the analysed photo is no longer held on the server (analyses expire "
                     "after 3 hours or when the server restarts). Analyse the photo again.")
MSG_FRESHNESS_FAILED = ("Freshness assessment failed on the server, so the condition of this food is unknown. "
                        "Inspect it yourself before eating.")


def head_freshness(rec, features, food: str | None) -> dict | None:
    """Freshness-head inference for `food` on a photo's embedding. None only when this recognizer has no freshness head
    support at all (test fakes); a missing model or unsupported food gives an explicit 'not_assessed' result, and a
    failure gives an explicit error result, never 'fresh'."""
    assess = getattr(rec, "assess_freshness", None)
    if assess is None or features is None or not food:
        return None
    try:
        return assess(features, food)
    except Exception:  # noqa: BLE001
        log.exception("freshness assessment failed")
        return {**NOT_ASSESSED, "model_status": "error", "message": MSG_FRESHNESS_FAILED}


def assess_photo_freshness(rec, photo: dict | None, food: str | None, missing_message: str = MSG_NO_PHOTO) -> dict:
    """Freshness of an analysed photo for the final food identity (accepted, confirmed or corrected)."""
    if photo is None:
        return annotate_freshness({**NOT_ASSESSED, "message": missing_message})
    if photo.get("poor"):
        return annotate_freshness({**NOT_ASSESSED, "message": "Freshness was not assessed because the photo quality is too low."})
    if photo.get("condition"):  # food-independent condition model, already run on the original photo
        return annotate_freshness(photo["condition"])
    found = head_freshness(rec, photo.get("features"), food)
    return annotate_freshness(found or photo.get("fallback") or {**NOT_ASSESSED, "message": "Freshness was not assessed."})


def photo_for(pending_id: str | None) -> dict | None:
    entry = analysis_store.get(pending_id) if pending_id else None
    return entry["result"] if entry and entry.get("kind") == "pending" else None


MSG_PACKAGED = ("This looks like a packaged product. Its nutrition depends on the exact product and is printed on its label, "
                "so generic reference values are not shown. Use Scan packaged food to read the label or barcode.")


def general_nutrition(food: str, category: str, serving_grams: float | None) -> tuple[dict | None, str | None]:
    if category == "Packaged Food":  # never present a generic record as a specific product's nutrition
        return None, MSG_PACKAGED
    found = usda.lookup(food, category, serving_grams)
    if found["status"] == "found":
        return found["nutrition"], None
    return None, found["message"]


def general_identification(food: str, category: str, oa: dict, vis: dict | None, serving_grams: float | None,
                           user: User | None, idempotency_key: str | None, confirmed_by_user: bool = False,
                           freshness: dict | None = None, extras: dict | None = None, image_ref: str | None = None,
                           nutrition_ref=None, class_names=None) -> dict:
    """Success response for a food outside the 24 classes. Nutrition only from a verified USDA match, never another food's values."""
    nut, nut_err = general_nutrition(food, category, serving_grams)
    alternative, nut_err = generic_alternative(food, nut, nut_err, nutrition_ref, class_names)
    vision_agrees = bool(vis and vis.get("status") == "agrees")
    if confirmed_by_user:
        message = f"You confirmed this food, which was suggested by {provider_name(oa)}. It is not one of the 24 foods the image model knows."
    else:
        message = (f"Identified by {provider_name(oa)}. It is not one of the 24 foods the SmartPlateAI image model was trained on, so that model "
                   "could not cross-check it" + (", but Google Vision agrees." if vision_agrees else "."))
    freshness = annotate_freshness(freshness or {"status": "not_assessed", "confidence": None,
                                                 "message": "Freshness is only assessed for foods the freshness model was trained on."})
    body = {
        "success": True,
        "image_ref": image_ref,
        "prediction": {"food": food, "class_id": None, "confidence": None, "confidence_percent": None, "margin": None, "top_k": []},
        # OpenAI gives no usable confidence score, so none is invented. Accepted on evidence: OpenAI named a specific food
        # clearly, the image model independently reported it is not one of its 24 foods, and Google Vision (if configured)
        # did not contradict it (a conflict turns the result into a confirmation request before this point).
        "requires_confirmation": False,
        "acceptance_basis": "user_confirmed" if confirmed_by_user else "openai_identification_without_score",
        "suggest_packaged_scan": category == "Packaged Food",
        "identification": {"food": food, "category": category, "source": "user_confirmed" if confirmed_by_user else "openai",
                           "supported_class": None,
                           "provider": provider_name(oa),
                           "verified_by": [provider_name(oa)] + (["Google Vision"] if vision_agrees else []) + (["You"] if confirmed_by_user else [])},
        "recognition": {"status": "openai_identified", "message": message, "openai_status": oa.get("status")},
        **({"confirmation": {"food": food, "source": "user_confirmed_suggestion"}} if confirmed_by_user else {}),
        "openai_vision": oa, "vision": vis, "freshness": freshness,
        "nutrition": nut, "nutrition_error": nut_err, "generic_alternative": alternative,
        "safety_alert": safety_alert(freshness, food),
        "precautions": for_food(food, freshness),
        "notes": [f"{provider_name(oa)} does not provide a calibrated confidence score, so none is shown.",
                  "Nutrition for foods outside the 24 classes is shown only when a USDA FoodData Central reference record clearly matches.",
                  *filter(None, [condition_note(freshness, food)])],
        "warnings": [],
        **(extras or {}),
    }
    body["analysis_id"] = analysis_store.put("fresh", dict(body))
    body["history"] = history.autosave(user, "fresh", dict(body), body["analysis_id"], history.clean_key(idempotency_key))
    return body


def _ask_provider(service, label: str, img, class_names: list[str]) -> dict:
    """One provider's identification. Never expose provider diagnostics or credentials to clients or logs."""
    try:
        state = service.availability()
        if state != "ready":
            return {"status": "unavailable", "reason": state, "provider": label}
        if not usage_limits.provider_call_allowed(usage_limits.PROVIDER_KEYS[label]):
            return {"status": "unavailable", "reason": usage_limits.DAILY_LIMIT_REACHED, "provider": label}
        return {**service.identify(img, class_names), "provider": label}
    except openai_vision.OpenAIVisionError as exc:
        log.warning("%s vision unavailable: %s", label, exc.code)
        return {"status": "unavailable", "reason": exc.code, "provider": label}
    except Exception as exc:  # noqa: BLE001
        log.error("%s vision failed (%s)", label, type(exc).__name__)
        return {"status": "unavailable", "reason": "provider_error", "provider": label}


def run_openai_vision(img, class_names: list[str]) -> dict:
    """General-purpose vision identification: OpenAI Vision first; Google Gemini only when OpenAI gave no answer (for
    example an account with no credit). One call per provider at most; the result says which provider answered."""
    oa = _ask_provider(openai_vision, "OpenAI Vision", img, class_names)
    if oa["status"] != "unavailable":
        return oa
    gm = _ask_provider(gemini_vision, gemini_vision.PROVIDER, img, class_names)
    if gm["status"] != "unavailable":
        return {**gm, "fallback_from": {"provider": "OpenAI Vision", "reason": oa["reason"]}}
    if gm["reason"] not in OPENAI_OFF:
        oa = {**oa, "fallback": {"provider": gemini_vision.PROVIDER, "reason": gm["reason"]}}
    return oa


def provider_name(oa: dict | None) -> str:
    return (oa or {}).get("provider") or "OpenAI Vision"


def for_provider(message: str, oa: dict | None) -> str:
    """Messages are written for OpenAI; name the provider that actually answered."""
    name = provider_name(oa)
    return message if name == "OpenAI Vision" else message.replace("OpenAI", name)


def recognition_summary(decision: str, oa: dict, agrees: bool, vis: dict | None) -> dict:
    if decision == "uncertain":
        status, message = "confirmation_required", "The recognition systems did not provide a verified, consistent result; confirm the food before using nutrition."
    elif decision == "unsupported_food":
        status, message = "unsupported_food", "The image appears to contain food outside the supported classes; no nutrition is provided."
    elif decision == "packaged_product":
        status, message = "packaged_product", "The photo looks like a package; no food was visible to identify."
    elif decision == "non_food":
        status, message = "non_food", "No recognizable food was identified."
    elif agrees and not (vis and vis.get("status") in ("conflicts", "no_food")):
        status, message = "verified_both", for_provider("TensorFlow and OpenAI identified the same supported food. OpenAI does not provide a "
                                                        "calibrated confidence score.", oa)
    else:
        status = "tensorflow_fallback"
        if vis and vis.get("status") == "agrees" and oa.get("reason") not in ("disabled", "not_configured"):
            message = "OpenAI was unavailable; Google Vision agrees with the image model's answer."
        elif oa.get("reason") == "disabled":
            message = "OpenAI recognition is disabled; this result uses the existing TensorFlow pipeline and Google Vision if configured."
        elif oa.get("reason") == "not_configured":
            message = "OpenAI recognition is not configured; this result uses the existing TensorFlow pipeline and Google Vision if configured."
        elif oa.get("reason") == "login_required":
            message = MSG_LOGIN_FOR_AI
        elif oa.get("reason") == usage_limits.DAILY_LIMIT_REACHED:
            message = MSG_DAILY_LIMIT
        elif oa.get("reason") == "quota_exhausted":
            fb = oa.get("fallback")
            message = (MSG_QUOTA + (f" The {fb['provider']} fallback also failed ({fb['reason'].replace('_', ' ')})." if fb else "") +
                       " This result comes from the SmartPlateAI image model alone, which knows only 24 foods, so a "
                       "food outside that list may be mislabelled as one of them.")
        else:
            message = "OpenAI recognition was unavailable; this result uses the existing TensorFlow pipeline and Google Vision if configured."
    return {"status": status, "message": message, "openai_status": oa.get("status")}


def run_vision(img, predicted: str | None, class_names: list[str]) -> dict | None:
    """Google Vision second opinion. Returns None when not configured; {'status': 'unavailable'} on failure."""
    if not vision.enabled():
        return None
    try:
        raw = vision.annotate(img)
    except vision.VisionUnavailable as exc:
        log.warning("vision unavailable: %s", str(exc)[:120])
        return {"status": "unavailable", "message": "Google Vision was unavailable, so only the image model was used."}
    except Exception:  # noqa: BLE001
        log.exception("vision failed")
        return {"status": "unavailable", "message": "Google Vision was unavailable, so only the image model was used."}
    out = vision.assess(raw, predicted, class_names)
    out["cached"] = raw.get("cached", False)
    return out


@router.get("/foods/supported")
def supported_foods(rec: FoodRecognizer = Depends(get_recognizer)):
    if not rec.load():
        return error("MODEL_UNAVAILABLE", rec.status_message, 503)
    return {"success": True, "foods": list(rec.class_names)}


@router.post("/analyze/confirm", dependencies=[Depends(limit("lookup"))])
def confirm_food(payload: ConfirmFoodRequest, rec: FoodRecognizer = Depends(get_recognizer),
                 nutrition: NutritionReference = Depends(get_nutrition), user: User | None = Depends(optional_user),
                 idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if not rec.load():
        return error("MODEL_UNAVAILABLE", rec.status_message, 503)
    food = payload.food.strip()
    if not food:
        return error("INVALID_FOOD_SELECTION", "Enter a food name before continuing.", 422)
    supported_food = next((name for name in rec.class_names if name.casefold() == food.casefold()), None)
    # The analysed photo this choice belongs to: freshness is assessed on it for the food chosen here, whatever the path.
    pend = photo_for(payload.pending_id)
    missing = MSG_PHOTO_EXPIRED if payload.pending_id else MSG_NO_PHOTO
    photo_extras = {k: pend[k] for k in ("image_quality", "enhancement") if k in pend} if pend else {}
    if supported_food is None:
        general = (pend or {}).get("general")
        if general and general.get("food", "").casefold() == food.casefold():
            return general_identification(general["food"], general["category"], {"status": "unsupported_food", "food_name": general["food"],
                                                                                  "provider": general.get("source")},
                                          None, payload.serving_grams, user, history.clean_key(idempotency_key), confirmed_by_user=True,
                                          freshness=assess_photo_freshness(rec, pend, general["food"], missing),
                                          extras=photo_extras, image_ref=payload.pending_id, nutrition_ref=nutrition,
                                          class_names=rec.class_names)
        category = food_category.resolve(food)
        nut, nut_err = general_nutrition(food, category, payload.serving_grams)
        alternative, nut_err = generic_alternative(food, nut, nut_err, nutrition, rec.class_names)
        freshness = assess_photo_freshness(rec, pend, food, missing)
        body = {
            "success": True,
            "image_ref": payload.pending_id if pend else None,
            "confirmation": {"food": food, "source": "user_selected"},
            "identification": {"food": food, "category": category, "source": "user_selected",
                               "supported_class": None, "verified_by": ["You"]},
            "freshness": freshness,
            "nutrition": nut,
            "nutrition_error": nut_err,
            "generic_alternative": alternative,
            "safety_alert": safety_alert(freshness, food),
            "precautions": for_food(food, freshness),
            "notes": [
                "This food name was entered by you and was not identified or verified by the image model.",
                "Nutrition values are shown only when a verified USDA reference record clearly matches; values may differ from the food photographed.",
                *filter(None, [condition_note(freshness, food)]),
            ],
            **photo_extras,
        }
        body["analysis_id"] = analysis_store.put("fresh", dict(body))
        body["history"] = history.autosave(user, "fresh", dict(body), body["analysis_id"], history.clean_key(idempotency_key))
        return body

    food = supported_food
    nut = nutrition.lookup(food, payload.serving_grams)
    choice = None if payload.accept_generic else specific_type_choice(food, nut)
    if choice:
        nut = None
    freshness = assess_photo_freshness(rec, pend, food, missing)
    body = {
        "success": True,
        "image_ref": payload.pending_id if pend else None,
        "confirmation": {"food": food, "source": "user_selected", **({"accepted_generic_reference": True} if is_category(food) and
                                                                     payload.accept_generic else {})},
        "identification": {"food": food, "category": food_category.resolve(food), "source": "user_selected",
                           "specificity": "category" if is_category(food) else "specific",
                           "specific_type": None if is_category(food) else food,
                           "supported_class": food, "verified_by": ["You"]},
        "freshness": freshness,
        "nutrition": nut,
        "nutrition_error": choice["message"] if choice else None if nut else (nutrition.error or "No nutrition reference record for this food."),
        "nutrition_choice": choice,
        "safety_alert": safety_alert(freshness, food),
        "precautions": for_food(food, freshness),
        "notes": [
            "This food was selected by you and was not independently verified by the model.",
            "Nutrition values are reference data and may differ from the photographed item.",
            *filter(None, [condition_note(freshness, food)]),
        ],
        **photo_extras,
    }
    body["analysis_id"] = analysis_store.put("fresh", dict(body))
    body["history"] = history.autosave(user, "fresh", dict(body), body["analysis_id"], history.clean_key(idempotency_key))
    return body


@router.get("/chemical/{food}", dependencies=[Depends(limit("lookup"))])
def chemical(food: str, rec: FoodRecognizer = Depends(get_recognizer), nutrition: NutritionReference = Depends(get_nutrition)):
    from app.services.chemistry import chemical_profile  # noqa: PLC0415
    known = list(rec.class_names) if rec.load() else []
    if known and food not in known:
        return error("INVALID_FOOD_SELECTION", "Chemical information is available only for the supported foods.", 422)
    nut = nutrition.lookup(food)
    if not known and nut is None:
        return error("INVALID_FOOD_SELECTION", "Unknown food.", 422)
    return chemical_profile(food, nut)