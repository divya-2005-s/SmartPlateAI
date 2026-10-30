"""Verified nutrition for meal-plan ingredients, from the project's existing data sources (never from the AI model).

For every ingredient with a gram amount, per-100 g values are taken from
  1. the project's nutrition reference CSV (USDA FoodData Central records for the 24 model foods), else
  2. the USDA FoodData Central search (app/services/usda.py; needs USDA_FDC_API_KEY, results cached),
and scaled to the grams given. Only compatible units are added (everything is converted to the canonical unit first).
A meal total is "complete" only when every ingredient has an amount and a verified match; otherwise the meal is
"partial" and the UI must not present the sum as the meal's total. Nothing is filled in for unmatched ingredients.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from app.services import nutrients as N
from app.services import usda

log = logging.getLogger("smartplate.meal_nutrition")
KEYS = ["energy_kcal", "protein_g", "carbohydrate_g", "total_sugars_g", "total_fat_g", "saturated_fat_g", "dietary_fibre_g", "sodium_mg"]
MAX_LOOKUPS = 40  # distinct ingredient names looked up per plan (USDA search is rate-limited)
LocalLookup = Callable[[str], "dict | None"]


def _per100(nutrition: dict) -> dict[str, float | None]:
    vals = N.canonicalise(nutrition.get("nutrients", []), "per_100g")
    return {k: vals.get(k) for k in KEYS}


def _candidates(name: str) -> list[str]:
    n = " ".join(name.lower().split())
    out = [n]
    if n.endswith("es") and len(n) > 4:
        out.append(n[:-2])
    if n.endswith("s") and len(n) > 3:
        out.append(n[:-1])
    return out


def resolve(name: str, local_lookup: LocalLookup | None) -> dict:
    """Per-100 g reference for one ingredient name: {'status': 'matched', 'per_100g', 'source'} or no_match / unavailable."""
    if local_lookup:
        for cand in _candidates(name):
            rec = local_lookup(cand)
            if rec:
                return {"status": "matched", "per_100g": _per100(rec),
                        "source": {"name": "USDA FoodData Central (project nutrition dataset)", "fdc_id": rec.get("source_fdc_id"),
                                   "description": rec.get("matched_description") or rec.get("basis"), "url": rec.get("source_url"),
                                   "generic_category_reference": bool(rec.get("generic_category_reference"))}}
    if not usda.enabled():
        return {"status": "unavailable", "message": "No local reference record; the USDA lookup is not configured on this server."}
    try:
        res = usda.lookup(name, "")
    except Exception:  # noqa: BLE001  - one failed lookup must not break the whole plan
        log.exception("USDA lookup failed for a meal ingredient")
        return {"status": "unavailable", "message": "The USDA lookup failed."}
    if res.get("status") != "found":
        return {"status": "no_match" if res.get("status") == "no_match" else "unavailable", "message": res.get("message")}
    nut = res["nutrition"]
    return {"status": "matched", "per_100g": _per100(nut),
            "source": {"name": "USDA FoodData Central", "fdc_id": nut.get("source_fdc_id"), "description": nut.get("matched_description"),
                       "data_type": nut.get("data_type"), "url": nut.get("source_url"), "generic_category_reference": False}}


def resolve_all(names: list[str], local_lookup: LocalLookup | None) -> dict[str, dict]:
    distinct = list(dict.fromkeys(n.lower().strip() for n in names if n and n.strip()))
    looked, skipped = distinct[:MAX_LOOKUPS], distinct[MAX_LOOKUPS:]
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = dict(zip(looked, ex.map(lambda n: resolve(n, local_lookup), looked)))
    for n in skipped:
        results[n] = {"status": "unavailable", "message": "Not looked up: too many different ingredients in this plan."}
    return results


def meal_verified(meal: dict, refs: dict[str, dict]) -> dict:
    rows, complete = [], True
    totals = {k: 0.0 for k in KEYS}
    known = {k: True for k in KEYS}
    for ing in meal.get("ingredients", []):
        ref = refs.get(ing["item"].lower().strip(), {"status": "unavailable"})
        grams = ing.get("grams")
        row = {"item": ing["item"], "grams": grams, "status": ref["status"], "source": ref.get("source"), "values": None,
               "message": ref.get("message")}
        if grams is None:
            row["status"], row["message"] = "no_amount", "No amount given, so this ingredient's nutrition cannot be calculated."
        if row["status"] == "matched":
            row["values"] = N.scale(ref["per_100g"], grams)
            for k in KEYS:
                v = row["values"].get(k)
                if v is None:
                    known[k] = False
                else:
                    totals[k] += v
        else:
            complete = False
        rows.append(row)
    matched = sum(r["status"] == "matched" for r in rows)
    status = "complete" if rows and complete else ("partial" if matched else "unavailable")
    return {"status": status, "ingredients": rows, "matched": matched, "total": len(rows),
            # Sums of the matched ingredients only. For a partial meal these are NOT the meal's totals.
            "totals": {k: (round(totals[k], 1) if known[k] and matched else None) for k in KEYS},
            "basis": "Calculated from USDA FoodData Central per-100 g reference values scaled to the gram amounts in the plan."}


def day_verified(meals: list[dict]) -> dict:
    """Day totals from meals whose verified nutrition is complete; 'complete' only when every meal is."""
    counted = [m for m in meals if not m.get("withheld")]
    done = [m for m in counted if (m.get("verified_nutrition") or {}).get("status") == "complete"]
    out = {}
    for k in KEYS:
        vals = [m["verified_nutrition"]["totals"].get(k) for m in done]
        out[k] = round(sum(vals), 1) if done and all(v is not None for v in vals) else None
    return {"complete": bool(counted) and len(done) == len(counted), "meals_counted": len(done), "meals": len(counted), "totals": out}
