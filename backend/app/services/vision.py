"""Google Cloud Vision (label detection + object localisation) as a second opinion for the food classifier.

Configured with GOOGLE_VISION_API_KEY (an API key restricted to the Cloud Vision API) in backend/.env. The image is
sent from the server only; the key never reaches the browser. Results are cached by image hash for 7 days.

Vision labels are never accepted as an exact food identity by themselves. They are used to:
  - confirm a classifier prediction ("agrees"),
  - flag a conflict ("conflicts"): Vision confidently names a different specific food -> the API asks the user to confirm,
  - flag "no_food": Vision sees no food at all -> the API asks the user to confirm,
  - offer hints for foods outside the 24 classes (shown as unverified suggestions, never with nutrition).
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import re
import time

from PIL import Image

from app.core.config import get_settings
from app.services import usage_limits
from app.services.http import ExternalError, cache_get, cache_key, cache_set, request_json

log = logging.getLogger("smartplate.vision")
URL = "https://vision.googleapis.com/v1/images:annotate"
CACHE_TTL = 7 * 24 * 3600
_VISION_BLOCKED_UNTIL = 0.0

GENERIC_FOOD = {
    "food", "ingredient", "recipe", "cuisine", "dish", "produce", "staple food", "natural foods", "fruit", "vegetable", "meal",
    "fast food", "junk food", "comfort food", "finger food", "snack", "baked goods", "superfood", "local food", "whole food",
    "vegan nutrition", "vegetarian food", "plant", "tableware", "plate", "seedless fruit", "citrus", "berry", "root vegetable",
    "leaf vegetable", "side dish", "breakfast", "lunch", "dinner", "indian cuisine", "street food", "fried food", "frying",
    "cooking", "dessert", "sweetness", "flowering plant", "terrestrial plant", "food group", "accessory fruit", "sweet",
}
NON_DISCRIMINATIVE = {"tableware", "plate", "plant", "flowering plant", "terrestrial plant", "sweetness"}
# Specific foods Vision commonly returns. Used only to recognise "a different specific food" conflicts.
COMMON_FOODS = {
    "apple", "banana", "orange", "mango", "grape", "strawberry", "pineapple", "watermelon", "papaya", "guava", "pomegranate", "lemon",
    "lime", "pear", "peach", "plum", "cherry", "kiwi", "coconut", "tomato", "potato", "onion", "garlic", "carrot", "cucumber",
    "cabbage", "cauliflower", "broccoli", "spinach", "eggplant", "brinjal", "okra", "capsicum", "bell pepper", "chili pepper", "pumpkin",
    "corn", "maize", "peas", "beans", "rice", "bread", "pizza", "burger", "hamburger", "sandwich", "hot dog", "taco", "burrito",
    "french fries", "noodles", "pasta", "spaghetti", "sushi", "salad", "soup", "curry", "dal", "biryani", "samosa", "dosa", "idli",
    "vada", "pakora", "chapati", "roti", "naan", "paratha", "puri", "paneer", "chole", "rajma", "khichdi", "upma", "poha", "jalebi",
    "gulab jamun", "ladoo", "cake", "cookie", "doughnut", "donut", "ice cream", "chocolate", "egg", "omelette", "chicken", "fish",
    "meat", "mutton", "prawn", "shrimp", "cheese", "milk", "yogurt", "curd", "tea", "coffee", "juice", "momo", "dumpling", "fried rice",
}
SYNONYMS = {"hamburger": "burger", "cheeseburger": "burger", "fries": "french fries", "chips": "french fries", "donut": "doughnut",
            "maize": "corn", "brinjal": "eggplant", "aubergine": "eggplant", "capsicum": "bell pepper", "chapati": "roti", "curd": "yogurt",
            "dumpling": "momo", "malus": "apple", "musa": "banana", "citrus sinensis": "orange"}


class VisionUnavailable(Exception):
    pass


def enabled() -> bool:
    s = get_settings()
    if time.monotonic() < _VISION_BLOCKED_UNTIL:
        return False
    return bool(s.vision_enabled and s.google_vision_api_key.strip())


def _block_vision_for(ttl_seconds: float = 900.0) -> None:
    global _VISION_BLOCKED_UNTIL
    _VISION_BLOCKED_UNTIL = time.monotonic() + ttl_seconds


def _norm(s: str) -> str:
    s = re.sub(r"[^a-z ]+", " ", s.lower()).strip()
    s = SYNONYMS.get(s, s)
    return re.sub(r"(es|s)$", "", s) if len(s) > 4 and not s.endswith("ss") else s


def _jpeg(img: Image.Image) -> bytes:
    im = img.copy()
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=85)
    return buf.getvalue()


def annotate(img: Image.Image) -> dict:
    if not enabled():
        raise VisionUnavailable("Google Vision is not configured.")
    data = _jpeg(img)
    key = cache_key("vision-v1", hashlib.sha256(data).hexdigest())
    cached = cache_get(key)
    if cached is not None:
        return {**cached, "cached": True}
    if not usage_limits.provider_call_allowed("google_vision"):
        raise VisionUnavailable("Google Vision daily limit reached on this server.")
    payload = {"requests": [{"image": {"content": base64.b64encode(data).decode()},
                             "features": [{"type": "LABEL_DETECTION", "maxResults": 12}, {"type": "OBJECT_LOCALIZATION", "maxResults": 8}]}]}
    try:
        resp = request_json(URL, method="POST", payload=payload, headers={"x-goog-api-key": get_settings().google_vision_api_key.strip()},
                            timeout=get_settings().http_timeout_s, retries=1)
    except ExternalError as exc:
        if exc.code in {"AUTH_FAILED", "BILLING_REQUIRED"}:
            _block_vision_for()
            hint = " Enable billing in the Google Cloud project or update GOOGLE_VISION_API_KEY in backend/.env; the app will continue without Vision until it is fixed."
            raise VisionUnavailable(f"Google Vision is unavailable: {exc.message}{hint}") from None
        raise VisionUnavailable(f"{exc.code}: {exc.message}") from None
    r = (resp.get("responses") or [{}])[0]
    if "error" in r:
        raise VisionUnavailable(f"Vision error: {r['error'].get('message', 'unknown')[:120]}")
    out = {"labels": [{"name": a.get("description", ""), "score": round(float(a.get("score", 0)), 3)} for a in r.get("labelAnnotations", [])],
           "objects": [{"name": o.get("name", ""), "score": round(float(o.get("score", 0)), 3)} for o in r.get("localizedObjectAnnotations", [])]}
    cache_set(key, out, CACHE_TTL)
    return {**out, "cached": False}


def assess(vision: dict, predicted: str | None, class_names: list[str], min_score: float | None = None) -> dict:
    """Compare Vision labels with the classifier's prediction. Pure function (unit-tested)."""
    min_score = get_settings().vision_min_score if min_score is None else min_score
    items = [(x["name"], x["score"]) for x in vision.get("labels", []) + vision.get("objects", [])]
    strong = [(n, s) for n, s in items if s >= min_score]
    classes = {_norm(c): c for c in class_names}
    pred = _norm(predicted) if predicted else None

    def matches(label: str, target: str) -> bool:
        lt, tt = set(_norm(label).split()), set(target.split())
        return bool(lt & tt) and (len(tt) == 1 or len(lt & tt) >= min(2, len(tt)))

    agrees = [n for n, s in strong if pred and matches(n, pred)]
    other_classes = [classes[c] for c in classes if c != pred and any(matches(n, c) for n, _ in strong)]
    specific = [n for n, _ in strong if _norm(n) in {_norm(f) for f in COMMON_FOODS} and not (pred and matches(n, pred))]
    food_related = [n for n, _ in strong if _norm(n) in {_norm(g) for g in GENERIC_FOOD - NON_DISCRIMINATIVE} or _norm(n) in
                    {_norm(f) for f in COMMON_FOODS} or any(matches(n, c) for c in classes)]
    if agrees:
        status = "agrees"
    elif other_classes or specific:
        status = "conflicts"
    elif not food_related:
        status = "no_food"
    else:
        status = "generic"
    hints = [n for n in specific if _norm(n) not in classes][:3]
    return {"status": status, "agreeing_labels": agrees[:3], "conflicting_supported_foods": other_classes[:3],
            "conflicting_labels": specific[:3], "hints_outside_supported": hints,
            "top_labels": [{"name": n, "score": s} for n, s in items[:8]]}
