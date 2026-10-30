"""Open Food Facts (https://world.openfoodfacts.org) as a supplementary product source.

- Barcode lookups are accepted only when the EAN/UPC check digit is valid and OFF returns that exact code.
- Name searches are accepted only when brand AND most product-name words match; otherwise they are returned as
  unconfirmed candidates.
- Values are labelled "Open Food Facts (crowd-sourced)"; conflicts with the photographed label are listed, and the
  label read from the actual pack takes priority.
Responses are cached for 3 days. Open Food Facts data is available under the Open Database Licence (ODbL).
"""
from __future__ import annotations

import difflib
import re

from app.core.config import get_settings
from app.services.http import ExternalError, build_url, cache_get, cache_key, cache_set, request_json
from app.services.label_parser import normalise_code

BASE = "https://world.openfoodfacts.org"
FIELDS = "code,product_name,brands,quantity,serving_size,ingredients_text,ingredients_text_en,allergens_tags,traces_tags,additives_tags,nutriments,url"
CACHE_TTL = 3 * 24 * 3600
OFF_TO_KEY = {  # OFF per-100 g field -> (canonical key, factor to canonical unit)
    "energy-kcal_100g": ("energy_kcal", 1.0), "proteins_100g": ("protein_g", 1.0), "carbohydrates_100g": ("carbohydrate_g", 1.0),
    "sugars_100g": ("total_sugars_g", 1.0), "fat_100g": ("total_fat_g", 1.0), "saturated-fat_100g": ("saturated_fat_g", 1.0),
    "trans-fat_100g": ("trans_fat_g", 1.0), "fiber_100g": ("dietary_fibre_g", 1.0), "sodium_100g": ("sodium_mg", 1000.0),
    "cholesterol_100g": ("cholesterol_mg", 1000.0), "calcium_100g": ("calcium_mg", 1000.0), "iron_100g": ("iron_mg", 1000.0),
}
OFF_ALLERGEN = {"milk": "milk", "eggs": "egg", "peanuts": "peanut", "nuts": "tree_nuts", "soybeans": "soy", "gluten": "wheat_gluten",
                "fish": "fish", "crustaceans": "crustaceans", "molluscs": "molluscs", "sesame-seeds": "sesame", "mustard": "mustard",
                "celery": "celery", "lupin": "lupin", "sulphur-dioxide-and-sulphites": "sulphites"}


def enabled() -> bool:
    return bool(get_settings().openfoodfacts_enabled)


def _check_ok(code: str) -> bool:
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def upce_to_upca(code: str) -> str | None:
    """Expand an 8-digit UPC-E code (number system 0 or 1) to its 12-digit UPC-A form; None if not UPC-E."""
    if not re.fullmatch(r"[01]\d{7}", code or ""):
        return None
    ns, d, check = code[0], code[1:7], code[7]
    last = d[5]
    if last in "012":
        body = d[0:2] + last + "0000" + d[2:5]
    elif last == "3":
        body = d[0:3] + "00000" + d[3:5]
    elif last == "4":
        body = d[0:4] + "00000" + d[4]
    else:
        body = d[0:5] + "0000" + last
    upca = ns + body + check
    return upca if _check_ok(upca) else None


def normalise_barcode(raw: str) -> dict:
    """Validate a barcode typed or scanned by the user. Leading zeros are kept (they are significant).
    Returns {'ok': bool, 'code': lookup code, 'format': 'EAN-13'|'EAN-8'|'UPC-A'|'UPC-E'|'GTIN-14', 'message'?}."""
    code = re.sub(r"[\s-]", "", raw or "")
    if not code.isdigit():
        return {"ok": False, "message": "A barcode may contain digits only."}
    if len(code) == 13 and _check_ok(code):
        return {"ok": True, "code": code, "format": "EAN-13"}
    if len(code) == 12 and _check_ok(code):
        return {"ok": True, "code": code, "format": "UPC-A"}
    if len(code) == 14 and _check_ok(code):
        return {"ok": True, "code": code, "format": "GTIN-14"}
    if len(code) == 8:
        if _check_ok(code):
            return {"ok": True, "code": code, "format": "EAN-8"}
        upca = upce_to_upca(code)
        if upca:
            return {"ok": True, "code": upca, "format": "UPC-E", "printed": code}
    if len(code) not in (8, 12, 13, 14):
        return {"ok": False, "message": "Barcodes have 8, 12, 13 or 14 digits (EAN-8, UPC-A, EAN-13 or GTIN-14)."}
    return {"ok": False, "message": "The check digit does not match. Re-check the digits printed under the barcode."}


def valid_barcode(code: str) -> bool:
    return normalise_barcode(code)["ok"]


def _product(p: dict) -> dict:
    nut = p.get("nutriments") or {}
    values = {}
    for f, (key, factor) in OFF_TO_KEY.items():
        v = nut.get(f)
        if isinstance(v, (int, float)):
            values[key] = round(float(v) * factor, 3)
    if "energy_kcal" not in values and isinstance(nut.get("energy_100g"), (int, float)):  # kJ only
        values["energy_kcal"] = round(float(nut["energy_100g"]) / 4.184, 1)
    tags = lambda name: [t.split(":", 1)[-1] for t in (p.get(name) or [])]  # noqa: E731
    additives = []
    for t in tags("additives_tags"):
        m = re.match(r"e(\d{3,4})([a-f])?(i{1,3}|iv|v)?", t)
        if m:
            c = normalise_code(m.group(1), m.group(2), m.group(3))
            if c:
                additives.append(c)
    return {"code": p.get("code"), "name": p.get("product_name") or None, "brand": (p.get("brands") or "").split(",")[0].strip() or None,
            "quantity": p.get("quantity") or None, "serving_size": p.get("serving_size") or None,
            "ingredients_text": p.get("ingredients_text_en") or p.get("ingredients_text") or None,
            "allergens": [OFF_ALLERGEN[t] for t in tags("allergens_tags") if t in OFF_ALLERGEN],
            "traces": [OFF_ALLERGEN[t] for t in tags("traces_tags") if t in OFF_ALLERGEN],
            "additive_codes": additives, "nutrition_per_100g": values,
            "url": f"{BASE}/product/{p.get('code')}" if p.get("code") else None,
            "source": "Open Food Facts (crowd-sourced, ODbL)"}


def by_barcode(code: str) -> dict:
    """Returns {'status': 'found'|'not_found'|'invalid'|'unavailable', 'reason'?: code, 'product'?: {...}, 'message': str}.
    'unavailable' carries reason DISABLED | TIMEOUT | RATE_LIMITED | UNREACHABLE | BAD_RESPONSE."""
    if not enabled():
        return {"status": "unavailable", "reason": "DISABLED", "message": "Open Food Facts lookups are disabled on this server."}
    norm = normalise_barcode(code)
    if not norm["ok"]:
        return {"status": "invalid", "message": norm["message"]}
    code = norm["code"]
    key = cache_key("off-barcode", code)
    cached = cache_get(key)
    if cached is not None:
        return {**cached, "barcode": code, "format": norm["format"], "cached": True}
    try:
        data = request_json(build_url(f"{BASE}/api/v2/product/{code}.json", {"fields": FIELDS}))
    except ExternalError as exc:
        if exc.code == "NOT_FOUND":
            res = {"status": "not_found", "message": "This barcode is not in Open Food Facts."}
            cache_set(key, res, CACHE_TTL)
            return {**res, "barcode": code, "format": norm["format"]}
        msg = {"TIMEOUT": "Open Food Facts did not answer in time. Please try again.",
               "RATE_LIMITED": "Open Food Facts is limiting requests right now. Please wait a minute and try again.",
               "UNREACHABLE": "Open Food Facts could not be reached. Check the internet connection."}.get(
            exc.code, "Open Food Facts returned an unexpected response.")
        return {"status": "unavailable", "reason": exc.code if exc.code in ("TIMEOUT", "RATE_LIMITED", "UNREACHABLE") else "BAD_RESPONSE",
                "message": msg, "barcode": code, "format": norm["format"]}
    if not isinstance(data, dict):
        return {"status": "unavailable", "reason": "BAD_RESPONSE", "message": "Open Food Facts returned an unexpected response.",
                "barcode": code, "format": norm["format"]}
    p = data.get("product")
    if data.get("status") != 1 or not isinstance(p, dict) or str(p.get("code", "")).lstrip("0") != code.lstrip("0"):
        res = {"status": "not_found", "message": "This barcode is not in Open Food Facts."}
    else:
        prod = _product(p)
        if not prod["name"] and not prod["brand"]:
            res = {"status": "not_found", "message": "Open Food Facts has this barcode but no product name or brand, so it cannot be identified."}
        else:
            res = {"status": "found", "match": "barcode", "product": prod}
    cache_set(key, res, CACHE_TTL)
    return {**res, "barcode": code, "format": norm["format"]}


def _tokens(s: str | None) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", (s or "").lower())}


def _close(a: str, b: str) -> bool:
    if a == b:
        return True
    return min(len(a), len(b)) >= 4 and abs(len(a) - len(b)) <= 2 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _found_share(wanted: set[str], have: set[str]) -> float:
    if not wanted:
        return 0.0
    return sum(1 for w in wanted if any(_close(w, h) for h in have)) / len(wanted)


_WEAK = {"with", "and", "the", "pack", "new", "flavour", "flavor", "taste", "instant", "food", "foods", "india", "pvt", "ltd"}


def search(name: str, brand: str | None = None, verify_text: str | None = None) -> dict:
    """Name search. A result is accepted only with independent evidence:
    - with `verify_text` (the text actually read from the pack): the product's brand AND at least 60% of its
      distinctive name words must appear in that text (spelling-tolerant), so a similar product is not accepted;
    - otherwise: the brand must match and 75% of the requested name words must be in the product name."""
    if not enabled():
        return {"status": "unavailable", "reason": "DISABLED", "message": "Open Food Facts lookups are disabled."}
    q = " ".join(filter(None, [brand, name])).strip()
    if not q:
        return {"status": "not_found", "candidates": [], "message": "Nothing to search for."}
    key = cache_key("off-search-raw", q.lower())
    raw = cache_get(key)
    if raw is None:
        try:
            data = request_json(build_url(f"{BASE}/cgi/search.pl", {"search_terms": q, "search_simple": 1, "json": 1, "page_size": 10,
                                                                     "fields": FIELDS}))
        except ExternalError as exc:
            return {"status": "unavailable", "reason": exc.code,
                    "message": f"Open Food Facts could not be reached ({exc.code}). The result is based on the label only."}
        if not isinstance(data, dict):
            return {"status": "unavailable", "reason": "BAD_RESPONSE", "message": "Open Food Facts returned an unreadable answer."}
        raw = [p for p in (data.get("products") or []) if isinstance(p, dict)][:10]
        cache_set(key, raw, CACHE_TTL)
    have = _tokens(verify_text) if verify_text else set()
    want_name, want_brand = _tokens(name), _tokens(brand)
    accepted, candidates = None, []
    for p in raw:
        prod = _product(p)
        if not (prod.get("name") or prod.get("brand")):
            continue
        if verify_text:
            p_brand = _tokens(prod["brand"]) - _WEAK
            p_name = (_tokens(prod["name"]) - _WEAK) - p_brand
            brand_share = _found_share(p_brand, have)
            name_share = _found_share(p_name, have)
            ok = brand_share >= 0.99 and name_share >= 0.6 and bool(p_name)
            cand = {**prod, "name_overlap": round(name_share, 2), "brand_match": brand_share >= 0.99, "verified_against_label": ok}
        else:
            name_overlap = len(want_name & _tokens(prod["name"])) / max(1, len(want_name))
            brand_ok = bool(want_brand) and bool(want_brand & _tokens(prod["brand"]))
            ok = brand_ok and name_overlap >= 0.75
            cand = {**prod, "name_overlap": round(name_overlap, 2), "brand_match": brand_ok}
        if accepted is None and ok:
            accepted = cand
        candidates.append(cand)
    if accepted:
        return {"status": "found", "match": "name_verified_against_label" if verify_text else "name_and_brand",
                "product": accepted, "candidates": candidates[:5], "query": q}
    return {"status": "unconfirmed" if candidates else "not_found", "candidates": candidates[:5], "query": q,
            "message": "Open Food Facts has similar products, but none matched both the brand and the product name read from the pack."
            if candidates else "Open Food Facts has no product for this search."}


def conflicts(label_values: dict[str, float], label_basis: str, off_values: dict[str, float], tolerance: float = 0.2) -> list[dict]:
    """Differences > 20 % (and > a small absolute amount) between the label read from the photo and OFF, per 100 g only."""
    if label_basis != "per 100 g":
        return []
    out = []
    for k, lv in label_values.items():
        ov = off_values.get(k)
        if ov is None or lv is None:
            continue
        diff = abs(lv - ov)
        if diff > tolerance * max(abs(lv), abs(ov)) and diff > (5 if k.endswith("_mg") else 0.5):
            out.append({"nutrient": k, "label_value": lv, "open_food_facts_value": ov})
    return out
