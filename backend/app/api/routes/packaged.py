"""Packaged-food analysis: label OCR -> label parsing -> dataset product match -> additives and precautions."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import User, optional_user, user_allergens
from app.api.limits import analysis_guard, limit
from app.api.limits import check as check_limit
from app.api.routes.analyze import MAX_BYTES, MAX_MB, error
from app.core.db import connect
from app.services import allergens as A
from app.services import analysis_store, gemini_vision, history, openai_vision, usage_limits
from app.services import nutrients as N
from app.services import openfoodfacts as off
from app.ml.recognizer import ImageError, decode_upload
from app.services import barcode_cv, ingredients_explain, ocr
from app.services.label_parser import parse_label
from app.services.packaged import PackagedFoodData, parse_quantity_g, text_tokens

log = logging.getLogger("smartplate.packaged")
router = APIRouter(prefix="/api", tags=["packaged"])

_data: PackagedFoodData | None = None
_lock = threading.Lock()

# UK Food Standards Agency front-of-pack "high" thresholds per 100 g (general guidance, not a medical rule).
HIGH_PER_100G = {"total_fat_g": (17.5, "fat"), "saturated_fat_g": (5.0, "saturated fat"), "total_sugars_g": (22.5, "sugars"),
                 "sodium_mg": (600.0, "sodium (salt)")}
NOTES = [
    "Label values are read by OCR and can contain reading errors; check them against the physical pack.",
    "Dataset values describe the matched product record, not this exact pack.",
    "SmartPlateAI cannot judge freshness, contamination or safety from a photo.",
]


def get_packaged_data() -> PackagedFoodData:
    global _data
    with _lock:
        if _data is None:
            _data = PackagedFoodData()
    return _data


def run_ocr(img):  # indirection so tests can replace OCR
    return ocr.ocr_image(img)


def run_front_ocr(img):  # front of pack: multi-variant OCR + text bands, words ranked by printed size
    return ocr.read_front(img)


def run_barcode(img):  # indirection so tests can replace barcode detection
    return barcode_cv.detect(img)


def precautions(label: dict, product_view: dict | None, additives: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen = set()
    # 1) high-in thresholds, only where the basis is known to be per 100 g
    sources = []
    if label["nutrition"]["basis"] == "per 100 g":
        sources.append(("package label", {k: v["value"] for k, v in label["nutrition"]["values"].items()}))
    if product_view and product_view["nutrition"]["basis_known"]:
        sources.append(("dataset record", {n["key"]: n["value"] for n in product_view["nutrition"]["nutrients"]}))
    for src, vals in sources:
        for key, (limit, word) in HIGH_PER_100G.items():
            v = vals.get(key)
            if v is not None and v > limit and key not in seen:
                seen.add(key)
                out.append({"kind": "guidance", "source": f"{src}; UK FSA per-100 g threshold",
                            "text": f"High in {word}: {v:g} per 100 g is above the {limit:g} 'high' threshold used on front-of-pack labels. "
                                    "Consider portion size and how often you eat it."})
    # 2) allergens read from the label
    for a in label["allergens"]:
        how = "may contain (trace) - " if a["may_contain_only"] else ""
        out.append({"kind": "allergen", "source": "package label (OCR): " + ", ".join(a["found_in"]),
                    "text": f"Allergen: {how}{a['allergen']}. Confirm on the physical label if you have an allergy."})
    if product_view and product_view.get("allergens_text"):
        out.append({"kind": "allergen", "source": "dataset record", "text": f"Dataset allergen information: {product_view['allergens_text']}"})
    # 3) additive notes from the dataset (reported, not endorsed)
    for ad in additives:
        if ad["notes"]:
            out.append({"kind": "additive", "source": f"{ad['source']} (unverified dataset text)",
                        "text": f"INS {ad['code']}{' (' + ad['name'] + ')' if ad['name'] else ''}: {ad['notes']}"})
    return out


def personal_alerts(user: User | None, ingredients_text: str | None, full_text: str, extra_declared=None, extra_traces=None) -> dict | None:
    if user is None:
        return None
    conn = connect()
    try:
        prefs = user_allergens(conn, user.id)
    finally:
        conn.close()
    det = A.detect(ingredients_text, full_text, extra_declared, extra_traces)
    return {**A.match_prefs(det, prefs), "detected": det["allergens"], "has_preferences": bool(prefs)}


def external_lookup(label: dict, product: dict | None, barcode: str | None = None) -> dict | None:
    """Open Food Facts for a product already matched in the dataset: barcode first, else brand + name. Used only to
    show extra information and conflicts; it never overrides the label."""
    if not off.enabled():
        return None
    code = barcode or label["identifiers"].get("barcode_digits")
    res = off.by_barcode(code) if code else None
    if (res is None or res["status"] != "found") and product and product.get("brand"):
        res = off.search(product["name"], product["brand"])
    if res is None:
        return {"status": "not_attempted", "message": "No barcode or confirmed product name to look up."}
    if res.get("status") == "found":
        res = {**res, "conflicts_with_label": off.conflicts({k: v["value"] for k, v in label["nutrition"]["values"].items()},
                                                            label["nutrition"]["basis"], res["product"]["nutrition_per_100g"])}
    return res


def detect_barcode(back_img, front_img, close_img=None) -> dict:
    """Decode the retail barcode from the photos (close-up, back, then front). Never raises."""
    for side, img in (("close-up", close_img), ("back", back_img), ("front", front_img)):
        if img is None:
            continue
        try:
            r = run_barcode(img)
        except Exception:  # noqa: BLE001
            log.exception("barcode detection failed")
            continue
        if r.get("status") == "found":
            return {**r, "side": side, "method": f"decoded from the bars in the {side} photo"}
    return {"status": "not_found", "code": None}


def _label_agrees(prod: dict, text: str) -> bool:
    """Does the text read from the pack contain the product's brand or most of its name? (spelling-tolerant)"""
    from app.services.packaged import similar  # noqa: PLC0415
    have = text_tokens(text)
    want = text_tokens(" ".join(filter(None, [prod.get("brand"), prod.get("name")])))
    if not want or not have:
        return False
    hits = sum(1 for w in want if any(similar(w, h) for h in have))
    return hits / len(want) >= 0.5


def external_identify(code: str | None, ai_identity: str, match: dict, prominent: list[str], text: str) -> dict | None:
    """The product is not (confidently) in the local dataset: try Open Food Facts.
    1) the barcode from the photo (exact identifier); 2) a name search whose result must be confirmed by the words
    read from the pack (brand + most name words). Failures are reported, never hidden."""
    if not off.enabled():
        return {"status": "unavailable", "reason": "DISABLED", "message": "Open Food Facts lookups are disabled."}
    if code:
        res = off.by_barcode(code)
        if res.get("status") == "found":
            agrees = _label_agrees(res["product"], text) if text.strip() else None
            return {**res, "match": "barcode", "verified_against_label": agrees,
                    "message": None if agrees is not False else
                    "The barcode belongs to this product, but its name was not found in the text read from the pack. Check the pack."}
        if res.get("status") == "unavailable":
            return res  # report the outage; do not pretend a name search is equivalent
    # Query with pack evidence first, else an anchored local candidate, else the largest printed words.
    # The external result still must be verified against the pack text below.
    anchored = [c for c in (match.get("candidates") or []) if (c.get("evidence") or {}).get("anchored")]
    query = ai_identity or (" ".join(filter(None, [anchored[0].get("brand"), anchored[0].get("name")])) if anchored else "") \
        or " ".join(prominent[:5])
    if not query.strip():
        return {"status": "not_attempted", "message": "No barcode or readable product name to look up."}
    return off.search(query, None, verify_text=text)


def identification(match: dict, product: dict | None, ext: dict | None, barcode: dict, prominent: list[str], ai_identity: str) -> dict:
    """One summary of how (and whether) the product was identified, with the evidence behind it."""
    detected = {"barcode": barcode.get("code"), "barcode_method": barcode.get("method"), "prominent_words": prominent,
                "vision_reading": ai_identity or None}
    if product is not None:
        return {"status": "identified", "source": "local dataset", "method": "barcode" if match.get("method") == "barcode" else "label text",
                "name": product["name"], "brand": product["brand"], "score": match["confidence"], "evidence": match["reason"],
                "detected": detected}
    if ext and ext.get("status") == "found":
        p = ext["product"]
        how = "barcode" if ext.get("match") == "barcode" else "name search confirmed by the label text"
        return {"status": "identified", "source": "Open Food Facts (crowd-sourced)", "method": how, "name": p.get("name"),
                "brand": p.get("brand"), "score": None,
                "evidence": (f"Barcode {p.get('code')} found in Open Food Facts." if how == "barcode" else
                             f"Open Food Facts product '{p.get('name')}' ({p.get('brand')}): its brand and name were found on the pack."),
                "detected": detected}
    status = "candidates" if match.get("candidates") or (ext and ext.get("candidates")) else "unidentified"
    return {"status": status, "source": None, "method": None, "name": None, "brand": None, "score": None,
            "evidence": match.get("reason"), "detected": detected}


OFF_ERRORS = {  # reason -> (error_code, HTTP status)
    "TIMEOUT": ("LOOKUP_TIMEOUT", 504), "RATE_LIMITED": ("LOOKUP_RATE_LIMITED", 429), "UNREACHABLE": ("LOOKUP_UNAVAILABLE", 503),
    "BAD_RESPONSE": ("LOOKUP_BAD_RESPONSE", 502), "DISABLED": ("LOOKUP_DISABLED", 503),
}


@router.get("/packaged/off/{barcode}", dependencies=[Depends(limit("lookup"))])
def off_barcode(barcode: str, user: User | None = Depends(optional_user),
                idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    """Barcode lookup. Success is HTTP 200 with success=true; every failure uses a real error status and an error_code
    (the old version returned HTTP 200 with success=false and no error_code, which the frontend reported as an
    'unexpected response (HTTP 200)')."""
    res = off.by_barcode(barcode.strip())
    fallback = "Try photographing the front and back of the pack, or search for the product by name."
    if res["status"] == "invalid":
        return error("INVALID_BARCODE", res["message"], 422)
    if res["status"] == "not_found":
        return error("PRODUCT_NOT_FOUND", f"{res['message']} {fallback}", 404, barcode=res.get("barcode"))
    if res["status"] != "found":
        code, status = OFF_ERRORS.get(res.get("reason", "BAD_RESPONSE"), ("LOOKUP_UNAVAILABLE", 503))
        return error(code, f"{res['message']} {fallback}", status, barcode=res.get("barcode"))
    p = res["product"]
    res["allergen_alerts"] = personal_alerts(user, p.get("ingredients_text"), "", p.get("allergens"), p.get("traces"))
    stored = {"success": True, "source": "barcode", "product": None, "label": {}, "match": {}, "external": res, "additives": [],
              "precautions": [], "allergen_alerts": res["allergen_alerts"]}
    res["analysis_id"] = analysis_store.put("packaged", dict(stored))
    res["history"] = history.autosave(user, "packaged", stored, res["analysis_id"], history.clean_key(idempotency_key))
    return {"success": True, **res}


@router.get("/packaged/status")
def packaged_status(data: PackagedFoodData = Depends(get_packaged_data)) -> dict:
    ok = data.load()
    return {"dataset_loaded": ok, "error": data.error, "products": len(data.products), "additive_codes_with_info": len(data.additive_info),
            "detected": data.detected, "ocr_available": ocr.tesseract_cmd() is not None}


class IngredientsExplainRequest(BaseModel):
    text: str = Field(min_length=1, max_length=ingredients_explain.MAX_TEXT)
    source: str | None = Field(default=None, max_length=120)  # e.g. "Tesseract OCR of the back label", "dataset record"
    uncertain: bool = False  # True when the text was read automatically from a photo


def additive_lookup(data: PackagedFoodData):
    """INS base code -> the project's additive reference record (name, function), or None."""
    if not data.load():
        return lambda code: None
    return lambda code: data.additive_info.get(code)


@router.post("/ingredients/explain", dependencies=[Depends(limit("lookup"))])
def explain_ingredients(body: IngredientsExplainRequest, data: PackagedFoodData = Depends(get_packaged_data)):
    """Plain-language explanation of an ingredient list the client already has. Reference data only; no AI provider."""
    return ingredients_explain.explain(body.text, body.source, body.uncertain, additive_lookup(data))


@router.get("/packaged/search")
def packaged_search(request: Request, q: str = Query(min_length=2, max_length=100), external: bool = Query(False),
                    data: PackagedFoodData = Depends(get_packaged_data), user: User | None = Depends(optional_user)):
    """Search by name (used when the pack could not be identified, or to correct the name). With external=true the
    Open Food Facts results are returned separately, so the user can pick a product that is not in the local dataset."""
    dataset_ok = data.load()
    if not dataset_ok and not external:
        return error("DATASET_UNAVAILABLE", data.error or "Packaged-food data is unavailable.", 503)
    body: dict = {"success": True, "results": data.search(q) if dataset_ok else [],
                  "dataset_error": None if dataset_ok else data.error}
    if external:
        check_limit("lookup", request, user)  # only the Open Food Facts search counts; the local dataset search is free
        res = off.search(q)
        items = res.get("candidates") or ([res["product"]] if res.get("product") else [])
        body["external"] = {"status": res.get("status"), "message": res.get("message"),
                            "results": [{"code": p.get("code"), "name": p.get("name"), "brand": p.get("brand"), "quantity": p.get("quantity")}
                                        for p in items if p.get("code")][:8]}
    return body


@router.get("/packaged/products/{product_id}")
def packaged_product(product_id: str, serving_grams: float | None = Query(None, ge=1, le=2000),
                     data: PackagedFoodData = Depends(get_packaged_data), user: User | None = Depends(optional_user)):
    if not data.load():
        return error("DATASET_UNAVAILABLE", data.error or "Packaged-food data is unavailable.", 503)
    rec = data.get(product_id)
    if rec is None:
        return error("PRODUCT_NOT_FOUND", "That product is not in the packaged-food dataset.", 404)
    view = data.product_view(rec, serving_grams)
    adds = data.additive_details(rec["additive_codes"])
    empty_label = {"nutrition": {"basis": "unknown", "values": {}}, "allergens": []}
    body = {"success": True, "product": view, "additives": adds, "precautions": precautions(empty_label, view, adds),
            "allergen_alerts": personal_alerts(user, view.get("ingredients_text"), view.get("allergens_text") or ""),
            "source": "user_selected", "notes": ["Selected by you from the dataset; not identified from the photo.", *NOTES[1:]]}
    body["analysis_id"] = analysis_store.put("packaged", dict(body))
    body["history"] = history.autosave(user, "packaged", dict(body), body["analysis_id"])
    return body


def _read_with(service, label: str, front, back) -> dict:
    try:
        state = service.availability()
        if state != "ready":
            return {"status": "unavailable", "reason": state, "provider": label}
        if not usage_limits.provider_call_allowed(usage_limits.PROVIDER_KEYS[label]):
            return {"status": "unavailable", "reason": usage_limits.DAILY_LIMIT_REACHED, "provider": label}
        return {"status": "ok", **service.read_package(front, back), "provider": label}
    except openai_vision.OpenAIVisionError as exc:
        log.warning("%s package reading unavailable: %s", label, exc.code)
        return {"status": "unavailable", "reason": exc.code, "provider": label}
    except Exception as exc:  # noqa: BLE001
        log.error("%s package reading failed (%s)", label, type(exc).__name__)
        return {"status": "unavailable", "reason": "provider_error", "provider": label}


def run_package_reading(front, back) -> dict:  # indirection so tests can replace the provider
    """AI reading of the label: OpenAI Vision first; Google Gemini only when OpenAI gave no answer (e.g. no credit)."""
    first = _read_with(openai_vision, "OpenAI Vision", front, back)
    if first["status"] == "ok":
        return first
    second = _read_with(gemini_vision, gemini_vision.PROVIDER, front, back)
    if second["status"] == "ok":
        return {**second, "fallback_from": {"provider": "OpenAI Vision", "reason": first["reason"]}}
    return first if second["reason"] in ("disabled", "not_configured") else {**first, "fallback": {"provider": second["provider"],
                                                                                                   "reason": second["reason"]}}


def reader_name(reading: dict | None) -> str:
    return (reading or {}).get("provider") or "OpenAI Vision"


def reader_short(reading: dict | None) -> str:
    return "OpenAI" if reader_name(reading) == "OpenAI Vision" else reader_name(reading)


def _read(upload: UploadFile | None, side: str):
    """Returns (image | None, error_response | None)."""
    if upload is None:
        return None, None
    raw = upload.file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        return None, error("FILE_TOO_LARGE", f"The {side} image is larger than {MAX_MB:g} MB. Please upload a smaller photo.", 413, side=side)
    if not raw:
        return None, error("INVALID_IMAGE", f"The {side} image is empty. Please choose a photo and try again.", 400, side=side)
    try:
        return decode_upload(raw), None
    except ImageError as exc:
        return None, error(exc.code, f"{side.capitalize()} image: {exc.message}", exc.status, side=side)


def _tokens(text: str | None) -> set[str]:
    import re  # noqa: PLC0415
    return {t for t in re.findall(r"[a-z0-9]{3,}", (text or "").lower())}


def consistency(reading: dict, front_text: str, back_text: str, have_front: bool, have_back: bool) -> dict:
    """Do the front and back images show the same product? Uses the AI judgement plus a brand-word check."""
    if not (have_front and have_back):
        return {"status": "single_image", "message": None}
    fb = (reading.get("front") or {}).get("brand") if reading.get("status") == "ok" else None
    bb = (reading.get("back") or {}).get("brand") if reading.get("status") == "ok" else None
    reasons = []
    if reading.get("status") == "ok" and reading.get("same_product") == "no":
        reasons.append(f"{reader_short(reading)} judged that the two photos show different products")
    if fb and bb and not (_tokens(fb) & _tokens(bb)):
        reasons.append(f"the brand on the front ('{fb}') differs from the brand on the back ('{bb}')")
    elif fb and back_text and not (_tokens(fb) & _tokens(back_text)) and len(_tokens(back_text)) > 40 and not bb:
        reasons.append(f"the front brand ('{fb}') does not appear anywhere in the back label text")
    if reasons:
        return {"status": "mismatch", "front_brand": fb, "back_brand": bb,
                "message": "These photos may be of different products: " + "; ".join(reasons) + "."}
    if reading.get("status") == "ok" and reading.get("same_product") == "yes":
        return {"status": "consistent", "front_brand": fb, "back_brand": bb, "message": None}
    return {"status": "unverified", "front_brand": fb, "back_brand": bb,
            "message": "Could not confirm that both photos show the same product; check that they do."}


def merge_label_nutrition(label: dict | None, reading: dict) -> dict:
    """Combine the Tesseract and OpenAI readings of the nutrition table, row by row, without inventing values.
    agree -> value shown; only one reader -> value shown with its source; disagree -> no value, both readings shown."""
    ocr_basis = (label or {}).get("nutrition", {}).get("basis", "unknown")
    ocr_vals = {k: v["value"] for k, v in ((label or {}).get("nutrition", {}).get("values") or {}).items() if k in N.CANONICAL}
    ai_rows = [r for r in ((reading.get("back") or {}).get("nutrients") or []) if r.get("key")] if reading.get("status") == "ok" else []
    # use the AI column whose basis matches the OCR basis; else the per-100 column; else whatever single basis exists
    bases = {r["basis"] for r in ai_rows}
    want = ocr_basis if ocr_basis in bases else ("per 100 g" if "per 100 g" in bases else "per 100 ml" if "per 100 ml" in bases
                                                 else (bases.pop() if len(bases) == 1 else None))
    ai_vals: dict[str, float] = {}
    for r in ai_rows:
        if r["basis"] == want and r["value"] is not None and r["key"] not in ai_vals:
            ai_vals[r["key"]] = r["value"]
    basis = ocr_basis if ocr_vals and ocr_basis != "unknown" else (want or ocr_basis)
    bases_agree = not (ocr_vals and ai_vals) or ocr_basis in ("unknown", want)
    rows = []
    for key in N.CANONICAL:
        o, a = ocr_vals.get(key), ai_vals.get(key) if bases_agree or not ocr_vals else None
        if o is None and a is None:
            continue
        label_, unit = N.CANONICAL[key][0], N.CANONICAL[key][1]
        if o is not None and a is not None:
            close = abs(o - a) <= max(0.1, 0.03 * max(abs(o), abs(a)))
            rows.append({"key": key, "label": label_, "unit": unit, "value": o if close else None, "ocr_value": o, "ai_value": a,
                         "status": "agree" if close else "conflict",
                         "source": f"package label (Tesseract OCR and {reader_short(reading)} agree)" if close else
                         "package label: readings disagree, check the pack"})
        else:
            v = o if o is not None else a
            rows.append({"key": key, "label": label_, "unit": unit, "value": v, "ocr_value": o, "ai_value": a,
                         "status": "ocr_only" if o is not None else "ai_only",
                         "source": "package label (Tesseract OCR)" if o is not None else f"package label ({reader_name(reading)} reading)"})
    return {"basis": basis, "rows": rows, "readers": [x for x, ok in (("tesseract", bool(ocr_vals)), ("openai" if reader_name(reading) == "OpenAI Vision" else "gemini", bool(ai_vals))) if ok],
            "note": None if bases_agree else "The two readings used different columns (per 100 g vs per serving), so only the OCR column is shown."}


@router.post("/analyze/packaged")
def analyze_packaged(file: UploadFile | None = File(None), front: UploadFile | None = File(None), back: UploadFile | None = File(None),
                     closeup: UploadFile | None = File(None),
                     serving_grams: float | None = Form(None), confirm_same_product: bool = Form(False),
                     data: PackagedFoodData = Depends(get_packaged_data), user: User | None = Depends(optional_user),
                     idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
                     _guard: None = Depends(analysis_guard)):
    """Packaged-food analysis. `front` (brand/product side) and/or `back` (ingredients and nutrition label).
    `file` is the original single-image field and is treated as the back label."""
    if serving_grams is not None and not (1 <= serving_grams <= 2000):
        return error("INVALID_SERVING", "Serving size must be between 1 and 2000 grams.", 422)
    if back is None and file is not None:
        back = file
    if front is None and back is None and closeup is None:
        return error("NO_IMAGE", "Upload a photo of the front and/or back of the package.", 422)
    front_img, err = _read(front, "front")
    if err:
        return err
    back_img, err = _read(back, "back")
    if err:
        return err
    close_img, err = _read(closeup, "close-up")
    if err:
        return err
    if back_img is None and close_img is not None:
        back_img, close_img = close_img, None

    t0 = time.time()
    ocr_ok, ocr_note = True, None
    o = {"text": "", "confidence": 0.0, "word_count": 0, "rotation": 0, "quality": "unreadable"}
    front_text, front_prominent = "", []
    back_ocr_text = ""
    # The independent steps run in parallel (Tesseract runs as a separate process, the providers are network calls).
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_back = pool.submit(run_ocr, back_img) if back_img is not None else None
        f_front = pool.submit(run_front_ocr, front_img) if front_img is not None else None
        f_close = pool.submit(run_ocr, close_img) if close_img is not None else None
        f_code = pool.submit(detect_barcode, back_img, front_img, close_img)
        # Anonymous on a public deployment: no paid label reading (Tesseract, barcode and Open Food Facts still run).
        f_read = pool.submit(run_package_reading, front_img, back_img) if usage_limits.paid_allowed(user) else None
        try:
            if f_back is not None:
                o = f_back.result()
                back_ocr_text = o["text"]
            if f_front is not None:
                fr = f_front.result()
                front_text, front_prominent = fr["text"], fr.get("prominent", [])
            if f_close is not None:
                oc = f_close.result()
                if oc["text"].strip():
                    o = {**o, "text": (o["text"] + "\n" + oc["text"]).strip(),
                         "word_count": o["word_count"] + oc["word_count"],
                         "quality": "good" if "good" in (o["quality"], oc["quality"]) else
                         "low" if "low" in (o["quality"], oc["quality"]) else o["quality"]}
        except ocr.OCRUnavailable as exc:
            log.warning("OCR unavailable: %s", exc)
            ocr_ok, ocr_note = False, "Tesseract OCR is not available on the server; only the OpenAI reading was used."
        except Exception:  # noqa: BLE001
            log.exception("OCR failed")
            return error("INTERNAL_ERROR", "Something went wrong while reading the label. Please try again.", 500)
        barcode = f_code.result()
        reading = f_read.result() if f_read is not None else {"status": "unavailable", "reason": "login_required",
                                                              "provider": "OpenAI Vision"}
    ai_ok = reading.get("status") == "ok"
    log.info("packaged ocr_words=%s ai=%s front=%s back=%s ms=%d", o["word_count"], reading.get("status"), front_img is not None,
             back_img is not None, (time.time() - t0) * 1000)
    if not ocr_ok and not ai_ok:
        return error("OCR_UNAVAILABLE", "Label reading (Tesseract OCR) is not available on the server and OpenAI label reading is "
                     f"unavailable ({reading.get('reason')}). Install Tesseract or set TESSERACT_CMD in backend/.env.", 503)
    ai_back_readable = ai_ok and reading["back"]["readable"]
    ai_front_readable = ai_ok and reading["front"]["readable"]
    if back_img is not None and o["quality"] == "unreadable" and not ai_back_readable and not (front_img is not None and (front_text.strip() or ai_front_readable)):
        return error("LABEL_UNREADABLE", "No readable label text was found. Photograph the label flat, close up and in good light, "
                     "or search for the product by name.", 422, ocr={"word_count": o["word_count"], "confidence": o["confidence"]})
    if front_img is not None and back_img is None and not front_text.strip() and not ai_front_readable:
        return error("LABEL_UNREADABLE", "The front of the package could not be read. Try a sharper, well-lit photo, or add the back label.", 422)

    check = consistency(reading, front_text, o["text"], front_img is not None, back_img is not None)
    if check["status"] == "mismatch" and not confirm_same_product:
        return error("PACKAGE_MISMATCH", check["message"] + " Retake the photos, or confirm that they are the same product.", 409,
                     consistency=check, requires_confirmation=True,
                     front={k: reading["front"].get(k) for k in ("brand", "product_name", "variant")} if ai_ok else None,
                     back={k: reading["back"].get(k) for k in ("brand", "product_name")} if ai_ok else None)

    label = parse_label(o["text"]) if o["text"] else parse_label("")
    if ai_back_readable:  # fill fields Tesseract could not read with the OpenAI reading of the same image (labelled)
        if not label["ingredients_text"] and reading["back"]["ingredients_text"]:
            label["ingredients_text"] = reading["back"]["ingredients_text"]
            label["ingredients_source"] = f"{reader_name(reading)} reading of the back label"
            from app.services.label_parser import extract_additive_codes  # noqa: PLC0415
            label["additive_codes"] = list(dict.fromkeys(label["additive_codes"] + extract_additive_codes(
                label["ingredients_text"], label["ingredients_text"])))
        elif label["ingredients_text"]:
            label["ingredients_source"] = "Tesseract OCR of the back label"
    label_nutrition = merge_label_nutrition(label if o["text"] else None, reading)

    ai_identity = " ".join(filter(None, [reading["front"].get("brand"), reading["front"].get("product_name"), reading["front"].get("variant"),
                                         reading["back"].get("brand"), reading["back"].get("product_name")])) if ai_ok else ""
    if not barcode.get("code") and label["identifiers"].get("barcode_digits"):
        barcode = {"status": "found", "code": label["identifiers"]["barcode_digits"], "method": "digits printed under the bars (OCR)"}
    match_text = "\n".join(filter(None, [ai_identity, " ".join(front_prominent), front_text, back_ocr_text]))
    net_g = parse_quantity_g((reading["front"].get("net_quantity") if ai_ok else None) or label["identifiers"].get("net_quantity"))
    dataset_ok = data.load()
    identity_text = "\n".join(filter(None, [ai_identity, " ".join(front_prominent), front_text])) or None
    match = data.match(match_text, barcode=barcode.get("code"), net_quantity_g=net_g, identity_text=identity_text) if dataset_ok and (match_text.strip() or barcode.get("code")) else (
        {"status": "unavailable", "method": None, "confidence": 0.0, "product_id": None, "candidates": [], "reason": data.error} if not dataset_ok else
        {"status": "unmatched", "method": None, "confidence": 0.0, "product_id": None, "candidates": [], "reason": "No text to match."})
    product = data.product_view(data.get(match["product_id"]), serving_grams) if match["status"] == "matched" else None
    ai_codes = []
    if ai_back_readable:
        from app.services.label_parser import extract_additive_codes  # noqa: PLC0415
        ai_codes = extract_additive_codes(" ".join(reading["back"]["additives"]), None)
    codes = list(dict.fromkeys(label["additive_codes"] + ai_codes + (product["additive_codes"] if product else [])))
    adds = data.additive_details(codes) if dataset_ok else [{"code": c, "ins_label": f"INS {c}", "name": None, "function": None,
                                                             "notes": None, "source": None, "in_reference": False} for c in codes]
    for ad in adds:
        ad["found_on_label"] = ad["code"] in label["additive_codes"] or ad["code"] in ai_codes
    unidentified_additives = [a for a in (reading["back"]["additives"] if ai_back_readable else [])
                              if not extract_codes_safe(a)]
    warnings = []
    if back_img is None:
        warnings.append("Only the front was provided, so ingredients and nutrition from the label are missing. Add a photo of the back label.")
    if back_img is not None and o["quality"] == "low":
        warnings.append("The label text was hard to read, so some values may be missing or wrong.")
    if ocr_note:
        warnings.append(ocr_note)
    if reading.get("reason") == "login_required":
        warnings.append("Sign in to add AI reading of the label (OpenAI / Google Gemini); only Tesseract OCR was used.")
    elif reading.get("reason") == usage_limits.DAILY_LIMIT_REACHED and not ai_ok:
        warnings.append("The server's daily limit for AI label reading has been reached; only Tesseract OCR was used.")
    elif not ai_ok and reading.get("reason") not in ("disabled", "not_configured"):
        fb = reading.get("fallback")
        warnings.append(f"OpenAI label reading was unavailable ({reading.get('reason')})"
                        + (f" and the {fb['provider']} fallback also failed ({fb['reason']})" if fb else "") + "; only Tesseract OCR was used.")
    if label["nutrition"].get("basis_note"):
        warnings.append(label["nutrition"]["basis_note"])
    if label["nutrition"].get("unreadable"):
        warnings.append("Some nutrition values could not be read reliably and are not shown: "
                        + ", ".join(u["label"] for u in label["nutrition"]["unreadable"]) + ". Check the pack.")
    if any(r["status"] == "conflict" for r in label_nutrition["rows"]):
        warnings.append("Some nutrition values were read differently by the two readers; those values are not shown. Check the pack.")
    if check["status"] == "mismatch":
        warnings.append("You confirmed that both photos show the same product, although they looked different.")
    elif check.get("message"):
        warnings.append(check["message"])
    full_text = " ".join(filter(None, [o["text"], " ".join(reading["back"]["allergen_statements"]) if ai_back_readable else ""]))
    ext = external_lookup(label, product, barcode.get("code")) if match["status"] == "matched" else \
        external_identify(barcode.get("code"), ai_identity, match, front_prominent, match_text)
    ident = identification(match, product, ext, barcode, front_prominent, ai_identity)
    if match["status"] != "matched":
        if ident["status"] == "identified":
            warnings.append("This product is not in the local dataset. It was identified in Open Food Facts (crowd-sourced); "
                            "check the details against the pack.")
        else:
            warnings.append("The product could not be identified with enough evidence. Pick it from the list, correct the name and "
                            "search again, or scan the barcode.")
    ext_p = ext["product"] if ext and ext.get("status") == "found" else {}
    alerts = personal_alerts(user, label["ingredients_text"] or (product or {}).get("ingredients_text"),
                             full_text + " " + ((product or {}).get("allergens_text") or ""), ext_p.get("allergens"), ext_p.get("traces"))
    if ai_back_readable:  # allergen statements read by OpenAI also feed the generic label allergen list
        from app.services.allergens import legacy_list  # noqa: PLC0415
        known = {a["allergen"] for a in label["allergens"]}
        label["allergens"] += [a for a in legacy_list(label["ingredients_text"], full_text) if a["allergen"] not in known]
    prec = precautions({**label, "nutrition": {"basis": label_nutrition["basis"],
                                               "values": {r["key"]: {"value": r["value"]} for r in label_nutrition["rows"] if r["value"] is not None}}},
                       product, adds)
    for d in label.get("dates", []):
        if d["type"].startswith("expiry"):
            prec.append({"kind": "guidance", "source": "package label (OCR, as printed)",
                         "text": f"Expiry information read from the label: '{d['as_printed']}'. Check it on the pack; OCR can misread digits."})
    for st in label.get("storage", []):
        prec.append({"kind": "guidance", "source": "package label (OCR, as printed)", "text": f"Storage instruction on the label: {st}."})
    for w in (reading["back"]["warnings"] if ai_back_readable else []):
        prec.append({"kind": "guidance", "source": f"package label ({reader_name(reading)} reading, as printed)", "text": w})
    if back_img is not None and not label.get("dates"):
        warnings.append("No manufacturing or expiry date could be read. Check the date on the pack.")
    identity = {
        "brand": (reading["front"].get("brand") or reading["back"].get("brand")) if ai_ok else None,
        "product_name": (reading["front"].get("product_name") or reading["back"].get("product_name")) if ai_ok else None,
        "variant": reading["front"].get("variant") if ai_ok else None,
        "package_type": reading["front"].get("package_type") if ai_ok else None,
        "net_quantity": (reading["front"].get("net_quantity") if ai_ok else None) or label["identifiers"].get("net_quantity"),
        "claims": reading["front"].get("claims", []) if ai_ok else [],
        "serving_size": (reading["back"].get("serving_size") if ai_back_readable else None),
        "manufacturer": (reading["back"].get("manufacturer") if ai_back_readable else None),
        "source": f"{reader_name(reading)} reading of the package (as printed)" if ai_ok else None,
    }
    images = {"front": front_img is not None, "back": back_img is not None}
    if close_img is not None:
        images["closeup"] = True
    body = {"success": True, "category": "Packaged Food",
            "images": images,
            "ocr": {"text": o["text"][:6000], "confidence": o["confidence"], "word_count": o["word_count"], "rotation": o["rotation"],
                    "quality": o["quality"], "front_text": front_text[:3000], "front_prominent": front_prominent},
            "package_reading": reading if ai_ok else {"status": "unavailable", "reason": reading.get("reason")},
            "identity": identity, "consistency": check, "label_nutrition": label_nutrition,
            "unidentified_additives": unidentified_additives,
            "label": label, "match": match, "product": product, "additives": adds, "external": ext, "allergen_alerts": alerts,
            "identification": ident, "barcode_detection": {k: barcode.get(k) for k in ("status", "code", "format", "method", "votes")},
            "precautions": prec, "warnings": warnings, "notes": NOTES}
    body["analysis_id"] = analysis_store.put("packaged", dict(body))
    body["history"] = history.autosave(user, "packaged", dict(body), body["analysis_id"], history.clean_key(idempotency_key))
    return body


def extract_codes_safe(text: str) -> list[str]:
    from app.services.label_parser import extract_additive_codes  # noqa: PLC0415
    import re  # noqa: PLC0415
    return extract_additive_codes(text, text) if re.search(r"\d{3}", text) else []
