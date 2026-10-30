"""OpenAI image-based food identification; all requests stay on the backend."""
from __future__ import annotations

import base64
import io
import json
import re
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from PIL import Image

from app.core.config import get_settings
from app.services.food_category import CATEGORIES

PROMPT = """Identify the visible food in this image for a food-analysis application.
Return only the requested structured fields. Do not infer ingredients, nutrition, freshness, or safety.
Set contains_food to false when no recognizable food is visible. If food is visible but its identity is unclear,
set food_name to null and explain the uncertainty. If a food is clear, name it plainly and as specifically as the image
shows: include the preparation state (e.g. cooked, raw, boiled, fried) and the type (e.g. white rice, plain dosa, paneer) only
when they are visible; never guess what is not visible. Do not include freshness or condition words in food_name.
The supported class names are provided below. Set supported_food only by using the exact class name when the
visible food clearly matches one of them; otherwise set it to null. Do not force a visually different food into
a supported class. No confidence/probability value is requested or should be inferred.
Set category to the best matching food group from the allowed list (Fruits, Vegetables, Cooked Dishes, Bakery Items, Snacks,
Beverages, Dairy, Grains & Cereals, Meat, Fish & Eggs, Packaged Food, Other), or null when no food is visible.
If several different foods are visible, name the main one and say so in uncertainty.
Supported class names: {classes}"""

FOOD_SCHEMA = {
    "type": "object",
    "properties": {
        "food_name": {"type": ["string", "null"]},
        "supported_food": {"type": ["string", "null"]},
        "visible_evidence": {"type": "array", "items": {"type": "string"}},
        "contains_food": {"type": "boolean"},
        "uncertainty": {"type": ["string", "null"]},
        "category": {"type": ["string", "null"], "enum": [*CATEGORIES, None]},
    },
    "required": ["food_name", "supported_food", "visible_evidence", "contains_food", "uncertainty", "category"],
    "additionalProperties": False,
}


class OpenAIVisionError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def availability() -> str:
    settings = get_settings()
    if not settings.openai_vision_enabled:
        return "disabled"
    if not settings.openai_api_key.strip():
        return "not_configured"
    return "ready"


def _jpeg(img: Image.Image) -> bytes:
    image = img.copy()
    image.thumbnail((1024, 1024))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=85, optimize=True)
    return buffer.getvalue()


def _parse_output(response: Any, class_names: list[str]) -> dict:
    output_text = getattr(response, "output_text", None)
    if not isinstance(output_text, str) or not output_text.strip():
        raise OpenAIVisionError("invalid_response")
    try:
        payload = json.loads(output_text)
    except (json.JSONDecodeError, TypeError):
        raise OpenAIVisionError("invalid_response") from None
    if not isinstance(payload, dict):
        raise OpenAIVisionError("invalid_response")

    name = payload.get("food_name")
    supported = payload.get("supported_food")
    evidence = payload.get("visible_evidence")
    contains_food = payload.get("contains_food")
    uncertainty = payload.get("uncertainty")
    if (
        (name is not None and (not isinstance(name, str) or not name.strip()))
        or (supported is not None and not isinstance(supported, str))
        or not isinstance(evidence, list)
        or len(evidence) > 8
        or any(not isinstance(item, str) for item in evidence)
        or not isinstance(contains_food, bool)
        or (uncertainty is not None and not isinstance(uncertainty, str))
    ):
        raise OpenAIVisionError("invalid_response")

    name = name.strip()[:120] if name else None
    uncertainty = uncertainty.strip()[:400] if uncertainty else None
    evidence = [item.strip()[:240] for item in evidence if item.strip()][:8]
    if (not contains_food and (name or supported)) or (not name and supported):
        raise OpenAIVisionError("invalid_response")

    # Treat the provider's supported label as untrusted input; only loaded model classes are accepted.
    class_by_key = {re.sub(r"[^a-z0-9]+", "", item.casefold()): item for item in class_names}
    name_food = class_for_name(name, class_names) if name else None
    reported_food = class_by_key.get(re.sub(r"[^a-z0-9]+", "", supported.casefold())) if supported else None
    conflicting_labels = bool(reported_food and name_food and reported_food != name_food)
    # The explicit food name is authoritative for class matching. Never allow the
    # separate supported_food field to force an unsupported name into a model class.
    supported_food = name_food if not conflicting_labels else None
    status = ("no_food" if not contains_food else "uncertain" if not name or conflicting_labels else
              "recognized" if supported_food else "unsupported_food")
    category = payload.get("category")
    return {
        "status": status,
        "food_name": strip_condition(name),
        "named_as": name,
        "supported_food": supported_food,
        "visible_evidence": evidence,
        "uncertainty": uncertainty,
        "category": category if category in CATEGORIES else None,
    }


# Words that describe colour, ripeness or cut but do not change which food it is ("red apple" -> Apple,
# "red onion" -> Onion). Words such as "sweet" or "custard" are NOT listed, so "sweet potato" never becomes Potato.
QUALIFIERS = {"red", "white", "yellow", "green", "golden", "purple", "black", "brown", "pink", "orange-colored", "fresh", "ripe",
              "unripe", "raw", "whole", "sliced", "chopped", "cut", "diced", "halved", "peeled", "small", "large", "big", "baby",
              "organic", "single", "one", "two", "a", "an", "of", "piece", "pieces", "some"}
CONDITION_WORDS = {"rotten", "rotting", "spoiled", "spoilt", "overripe", "over-ripe", "moldy", "mouldy", "decayed", "decaying",
                   "bruised", "damaged", "stale", "old", "wilted", "withered", "shrivelled", "shriveled", "fermented", "blackened",
                   "spotted", "browned", "mushy", "soft", "dried-out"}
QUALIFIERS |= CONDITION_WORDS


def strip_condition(name: str | None) -> str | None:
    """Remove condition descriptors from food identity without collapsing distinct foods."""
    if not name:
        return name
    words = [w for w in re.split(r"\s+", name.strip()) if w.casefold().strip(",.") not in CONDITION_WORDS]
    return " ".join(words) or name


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _singular(word: str) -> str:
    for suf, rep_ in (("ies", "y"), ("oes", "o"), ("es", "e"), ("s", "")):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)] + rep_
    return word


def class_for_name(name: str, class_names: list[str]) -> str | None:
    """Exact (normalised) class match first; then the same match after removing descriptive qualifiers and plurals."""
    by_key = {_key(c): c for c in class_names}
    exact = by_key.get(_key(name))
    if exact:
        return exact
    words = [w for w in re.findall(r"[a-z]+", name.casefold())]
    core = [_singular(w) for w in words if w not in QUALIFIERS]
    if not core:
        return None
    by_core = {}
    for c in class_names:
        ck = " ".join(_singular(w) for w in re.findall(r"[a-z]+", c.casefold()) if w not in QUALIFIERS)
        by_core.setdefault(ck, c)
    return by_core.get(" ".join(core))


def identify(img: Image.Image, class_names: list[str]) -> dict:
    """Send a resized, metadata-free JPEG and validate the structured response."""
    settings = get_settings()
    if availability() != "ready":
        raise OpenAIVisionError(availability())
    image_data = base64.b64encode(_jpeg(img)).decode("ascii")
    classes = json.dumps(class_names, ensure_ascii=True)
    try:
        client = OpenAI(
            api_key=settings.openai_api_key.strip(),
            timeout=settings.openai_vision_timeout_s,
            max_retries=0,
        )
        response = client.responses.create(
            model=settings.openai_vision_model,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": PROMPT.format(classes=classes)},
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{image_data}"},
                ],
            }],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "food_identification",
                    "strict": True,
                    "schema": FOOD_SCHEMA,
                },
            },
        )
    except APITimeoutError:
        raise OpenAIVisionError("timeout") from None
    except (AuthenticationError, PermissionDeniedError):
        raise OpenAIVisionError("authentication_failed") from None
    except RateLimitError as exc:
        raise OpenAIVisionError(rate_limit_reason(exc)) from None
    except APIConnectionError:
        raise OpenAIVisionError("network_error") from None
    except APIStatusError:
        raise OpenAIVisionError("provider_error") from None
    except (TimeoutError, ConnectionError, OSError):
        raise OpenAIVisionError("network_error") from None
    return _parse_output(response, class_names)


def rate_limit_reason(exc: Exception) -> str:
    """HTTP 429 means either a short-term rate limit or an account with no remaining credit (a persistent failure that
    retrying cannot fix). Only the provider's error type/code is inspected; nothing is logged or returned."""
    body = getattr(exc, "body", None)
    err = body.get("error", body) if isinstance(body, dict) else {}
    markers = {str(getattr(exc, "code", "") or ""), str((err or {}).get("type") or ""), str((err or {}).get("code") or "")}
    return "quota_exhausted" if markers & {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached"} else "rate_limited"


# ---------------------------------------------------------------------------- packaged food (front / back images)
PACKAGE_PROMPT = """You are reading photographs of ONE packaged food product for a nutrition app.
{images}
Copy text exactly as printed. Never guess, complete or infer values that are not clearly legible; use null or an empty list.
front: brand, product name, variant/flavour, package type (e.g. pouch, box, bottle, can, jar, wrapper) and net quantity as printed,
and short label claims (e.g. "no added sugar"). back: the ingredients list as printed, serving size as printed, the nutrition table
rows (name, amount as a number, unit as printed, and the column basis such as "per 100 g", "per 100 ml" or "per serving"),
allergen statements ("Contains ...", "May contain ..."), additive names or INS/E codes as printed, manufacturer/marketer line,
and warnings. Set readable=false for a side that was not provided or cannot be read.
same_product: "yes" if brand/product on both images clearly match, "no" if they clearly differ, "unclear" otherwise or if only one image."""

_STR = {"type": ["string", "null"]}
_LIST = {"type": "array", "items": {"type": "string"}}
PACKAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "front": {"type": "object", "additionalProperties": False,
                  "required": ["readable", "brand", "product_name", "variant", "package_type", "net_quantity", "claims"],
                  "properties": {"readable": {"type": "boolean"}, "brand": _STR, "product_name": _STR, "variant": _STR,
                                 "package_type": _STR, "net_quantity": _STR, "claims": _LIST}},
        "back": {"type": "object", "additionalProperties": False,
                 "required": ["readable", "brand", "product_name", "ingredients_text", "serving_size", "nutrients",
                              "allergen_statements", "additives", "manufacturer", "warnings"],
                 "properties": {"readable": {"type": "boolean"}, "brand": _STR, "product_name": _STR, "ingredients_text": _STR,
                                "serving_size": _STR,
                                "nutrients": {"type": "array", "items": {
                                    "type": "object", "additionalProperties": False, "required": ["name", "amount", "unit", "basis"],
                                    "properties": {"name": {"type": "string"}, "amount": {"type": "number"}, "unit": {"type": "string"},
                                                   "basis": {"type": "string"}}}},
                                "allergen_statements": _LIST, "additives": _LIST, "manufacturer": _STR, "warnings": _LIST}},
        "same_product": {"type": "string", "enum": ["yes", "no", "unclear"]},
    },
    "required": ["front", "back", "same_product"],
    "additionalProperties": False,
}


def _s(v, n: int = 300) -> str | None:
    return v.strip()[:n] if isinstance(v, str) and v.strip() else None


def _strs(v, n: int = 200, k: int = 20) -> list[str]:
    return [x.strip()[:n] for x in v if isinstance(x, str) and x.strip()][:k] if isinstance(v, list) else []


def _basis(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"100\s*m?l", t):
        return "per 100 ml"
    if re.search(r"100\s*g", t):
        return "per 100 g"
    if re.search(r"serv|portion|pack|piece", t):
        return "per serving"
    return "unknown"


def parse_package(response: Any) -> dict:
    """Validate the structured package reading. Values that fail validation are dropped, never repaired."""
    from app.services import nutrients as N  # noqa: PLC0415
    text = getattr(response, "output_text", None)
    try:
        payload = json.loads(text) if isinstance(text, str) else None
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get("front"), dict) or not isinstance(payload.get("back"), dict):
        raise OpenAIVisionError("invalid_response")
    f, b = payload["front"], payload["back"]
    nutrients = []
    for row in b.get("nutrients") or []:
        if not isinstance(row, dict) or not isinstance(row.get("amount"), (int, float)) or not isinstance(row.get("name"), str):
            continue
        amount = float(row["amount"])
        if not 0 <= amount <= 100000:
            continue
        key = N.canonical_key(row["name"])
        unit = N.norm_unit(row.get("unit") if isinstance(row.get("unit"), str) else None)
        value = N.convert(amount, unit, N.CANONICAL[key][1]) if key else None
        if key == "energy_kcal" and unit not in ("kcal", "kj", None):
            value = None
        nutrients.append({"name": row["name"].strip()[:60], "amount": amount, "unit": (row.get("unit") or "")[:12],
                          "basis": _basis(row.get("basis", "")), "key": key,
                          "value": None if value is None else round(value, 4)})
    same = payload.get("same_product") if payload.get("same_product") in ("yes", "no", "unclear") else "unclear"
    return {
        "front": {"readable": f.get("readable") is True, "brand": _s(f.get("brand"), 80), "product_name": _s(f.get("product_name"), 120),
                  "variant": _s(f.get("variant"), 80), "package_type": _s(f.get("package_type"), 40),
                  "net_quantity": _s(f.get("net_quantity"), 40), "claims": _strs(f.get("claims"), 120, 10)},
        "back": {"readable": b.get("readable") is True, "brand": _s(b.get("brand"), 80), "product_name": _s(b.get("product_name"), 120),
                 "ingredients_text": _s(b.get("ingredients_text"), 3000), "serving_size": _s(b.get("serving_size"), 60),
                 "nutrients": nutrients[:40], "allergen_statements": _strs(b.get("allergen_statements"), 300, 6),
                 "additives": _strs(b.get("additives"), 80, 40), "manufacturer": _s(b.get("manufacturer"), 300),
                 "warnings": _strs(b.get("warnings"), 300, 8)},
        "same_product": same,
    }


def read_package(front: Image.Image | None, back: Image.Image | None) -> dict:
    """One OpenAI request for the front and/or back image of the same pack."""
    settings = get_settings()
    if availability() != "ready":
        raise OpenAIVisionError(availability())
    content: list[dict] = []
    labels = []
    for role, img in (("FRONT", front), ("BACK", back)):
        if img is not None:
            labels.append(f"Image {len(labels) + 1} is the {role} of the package.")
            content.append({"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(_jpeg_label(img)).decode("ascii")})
    if not content:
        raise OpenAIVisionError("invalid_request")
    missing = [r for r, i in (("FRONT", front), ("BACK", back)) if i is None]
    note = " ".join(labels) + (f" No {missing[0]} image was provided." if missing else "")
    content.insert(0, {"type": "input_text", "text": PACKAGE_PROMPT.format(images=note)})
    try:
        client = OpenAI(api_key=settings.openai_api_key.strip(), timeout=settings.openai_vision_timeout_s, max_retries=0)
        response = client.responses.create(
            model=settings.openai_vision_model,
            input=[{"role": "user", "content": content}],
            text={"format": {"type": "json_schema", "name": "package_reading", "strict": True, "schema": PACKAGE_SCHEMA}},
        )
    except APITimeoutError:
        raise OpenAIVisionError("timeout") from None
    except (AuthenticationError, PermissionDeniedError):
        raise OpenAIVisionError("authentication_failed") from None
    except RateLimitError as exc:
        raise OpenAIVisionError(rate_limit_reason(exc)) from None
    except APIConnectionError:
        raise OpenAIVisionError("network_error") from None
    except APIStatusError:
        raise OpenAIVisionError("provider_error") from None
    except (TimeoutError, ConnectionError, OSError):
        raise OpenAIVisionError("network_error") from None
    return parse_package(response)


def _jpeg_label(img: Image.Image) -> bytes:
    """Labels need more pixels than whole-food photos for small print."""
    image = img.copy()
    image.thumbnail((2048, 2048))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=88, optimize=True)
    return buffer.getvalue()
