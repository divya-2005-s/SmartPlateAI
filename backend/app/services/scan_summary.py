"""Build a compact, provenance-labelled summary of an analysis result for history, the dashboard and reports."""
from __future__ import annotations

from app.services import nutrients as N


ID_LABELS = {
    "image_model_and_openai": "Recognised by the image model and confirmed by OpenAI Vision",
    "image_model": "Recognised by the image model (not cross-checked by OpenAI)",
    "openai": "Identified by OpenAI Vision (outside the image model's 24 classes)",
    "user_confirmed": "Confirmed by you from an OpenAI Vision suggestion",
    "user_selected": "Selected by you; not verified by the model",
}


def _fresh(result: dict) -> dict:
    pred = result.get("prediction")
    conf = result.get("confirmation")
    ident = result.get("identification")
    if ident:
        title = ident["food"]
        identity = {"food": ident["food"], "source": ident["source"],
                    "confidence": (pred or {}).get("confidence") if ident["source"].startswith("image_model") else None,
                    "label": ID_LABELS.get(ident["source"], ident["source"]), "category": ident.get("category"),
                    "verified_by": ident.get("verified_by", [])}
    elif pred:
        title, identity = pred["food"], {"food": pred["food"], "source": "model", "confidence": pred.get("confidence"),
                                          "label": "Recognised by the image model (a score, not a guarantee)"}
    else:
        title, identity = conf["food"], {"food": conf["food"], "source": "user_selected", "confidence": None,
                                          "label": "Selected by the user; not verified by the model"}
    nut = result.get("nutrition")
    per100 = N.canonicalise(nut["nutrients"], "per_100g") if nut else None
    return {
        "kind": "fresh", "title": title, "identity": identity, "category": identity.get("category"),
        "freshness": result.get("freshness"),
        "nutrition": {"per_100g": per100, "basis_known": bool(per100), "serving_grams": nut.get("serving_grams") if nut else None,
                      "source": nut["basis"] if nut else None, "provenance": "reference" if nut else None,
                      "not_available": nut.get("not_available", []) if nut else ([result["nutrition_error"]] if result.get("nutrition_error") else [])},
        "allergens": [], "additives": [],
        "precautions": [p["text"] for p in result.get("precautions", [])][:12],
    }


def _packaged(result: dict) -> dict:
    product = result.get("product")
    label = result.get("label") or {}
    match = result.get("match") or {}
    ext = result.get("external") or {}
    if result.get("source") == "barcode" and ext.get("status") == "found":
        p = ext["product"]
        title = " ".join(x for x in (p.get("brand"), p.get("name")) if x) or f"Barcode {ext.get('barcode')}"
        per100 = {k: v for k, v in (p.get("nutrition_per_100g") or {}).items() if k in N.CANONICAL} or None
        return {"kind": "packaged", "title": title, "category": "Packaged Food",
                "identity": {"food": title, "source": "barcode", "confidence": None,
                             "label": f"Barcode {ext.get('barcode')} looked up in Open Food Facts (crowd-sourced database)"},
                "freshness": None,
                "nutrition": {"per_100g": per100, "basis_known": bool(per100), "serving_grams": None, "source": p.get("source"),
                              "provenance": "external_database" if per100 else None,
                              "not_available": [] if per100 else ["Open Food Facts has no per-100 g nutrition for this product"]},
                "allergens": [f"{a} (database)" for a in p.get("allergens", [])] + [f"may contain {a} (database)" for a in p.get("traces", [])],
                "additives": [f"INS {c}" for c in p.get("additive_codes", [])], "personal_alerts": result.get("allergen_alerts"),
                "ingredients": p.get("ingredients_text"), "precautions": [], "source_url": p.get("url")}
    ident_ai = result.get("identity") or {}
    if product:
        title = " ".join(x for x in (product.get("brand"), product["name"]) if x)
        src = "user_selected" if result.get("source") == "user_selected" else "dataset_match"
        identity = {"food": title, "source": src, "confidence": match.get("confidence") if src == "dataset_match" else None,
                    "label": "Selected by the user from the dataset" if src == "user_selected" else "Matched to a dataset product from label text"}
    elif (result.get("identification") or {}).get("status") == "identified" and ext.get("status") == "found":
        idf = result["identification"]
        title = " ".join(x for x in (idf.get("brand"), idf.get("name")) if x) or "Packaged product"
        identity = {"food": title, "source": "open_food_facts", "confidence": None,
                    "label": f"Identified in Open Food Facts via {idf.get('method')} (not in the local dataset)"}
    else:
        title = (" ".join(x for x in (ident_ai.get("brand"), ident_ai.get("product_name"), ident_ai.get("variant")) if x)
                 or label.get("product_name_candidate") or "Unidentified packaged product")
        identity = {"food": title, "source": "unidentified", "confidence": None, "label": "Product not identified; label text only"}
    per100, provenance, source, basis_known = None, None, None, False
    if product and product["nutrition"]["basis_known"]:
        per100 = {n["key"]: n["value"] for n in product["nutrition"]["nutrients"]}
        per100 = {k: v for k, v in per100.items() if k in N.CANONICAL}
        provenance, source, basis_known = "dataset", product["nutrition"]["source"], True
    elif (result.get("label_nutrition") or {}).get("basis") == "per 100 g" and any(
            r["value"] is not None for r in result["label_nutrition"]["rows"]):
        per100 = {r["key"]: r["value"] for r in result["label_nutrition"]["rows"] if r["key"] in N.CANONICAL}
        provenance, source, basis_known = "package_label", "package label (" + " + ".join(result["label_nutrition"]["readers"]) + ")", True
    elif label.get("nutrition", {}).get("basis") == "per 100 g" and label["nutrition"]["values"]:
        per100 = {k: v["value"] for k, v in label["nutrition"]["values"].items() if k in N.CANONICAL}
        provenance, source, basis_known = "package_label", "package label (OCR)", True
    elif identity["source"] == "open_food_facts" and (ext.get("product") or {}).get("nutrition_per_100g"):
        per100 = {k: v for k, v in ext["product"]["nutrition_per_100g"].items() if k in N.CANONICAL}
        provenance, source, basis_known = "external_database", ext["product"].get("source"), True
    allergens = [a.get("allergen") for a in label.get("allergens", [])]
    if product and product.get("allergens_text"):
        allergens.append(f"dataset: {product['allergens_text']}")
    return {
        "kind": "packaged", "title": title, "identity": identity, "freshness": None, "category": "Packaged Food",
        "ingredients": label.get("ingredients_text") or (product or {}).get("ingredients_text"),
        "nutrition": {"per_100g": per100, "basis_known": basis_known, "serving_grams": None, "source": source, "provenance": provenance,
                      "not_available": [] if per100 else ["Nutrition per 100 g is not known for this product"]},
        "allergens": allergens,
        "additives": [a["ins_label"] + (f" ({a['name']})" if a.get("name") else "") for a in result.get("additives", [])],
        "personal_alerts": result.get("allergen_alerts"),
        "precautions": [p["text"] for p in result.get("precautions", [])][:12],
    }


def summarise(kind: str, result: dict) -> dict:
    return _fresh(result) if kind == "fresh" else _packaged(result)
