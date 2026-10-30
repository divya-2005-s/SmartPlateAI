"""BMI calculator and packaged-product comparison."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import User, optional_user
from app.api.routes.analyze import error
from app.api.routes.packaged import get_packaged_data
from app.core.db import connect
from app.services import allergens as A
from app.services.bmi import BMIError, calculate, to_metric
from app.services.packaged import PackagedFoodData

router = APIRouter(prefix="/api", tags=["tools"])


class BMIIn(BaseModel):
    height_cm: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    height_ft: float | None = Field(default=None, ge=0, le=9)
    height_in: float | None = Field(default=None, ge=0, lt=120)
    weight_lb: float | None = Field(default=None, gt=0)
    age: int | None = Field(default=None, ge=2, le=120)


@router.post("/tools/bmi")
def bmi(body: BMIIn):
    try:
        h, w = to_metric(body.height_cm, body.weight_kg, body.height_ft, body.height_in, body.weight_lb)
    except BMIError as exc:
        return error("INVALID_INPUT", str(exc), 422)
    return {"success": True, **calculate(h, w, body.age)}


# ------------------------------------------------------------------ comparison
PRIORITIES = {
    "lower_energy": ("energy_kcal", "min", "lower energy"),
    "lower_sugar": ("total_sugars_g", "min", "lower sugar"),
    "lower_sodium": ("sodium_mg", "min", "lower sodium"),
    "lower_saturated_fat": ("saturated_fat_g", "min", "lower saturated fat"),
    "lower_fat": ("total_fat_g", "min", "lower total fat"),
    "higher_protein": ("protein_g", "max", "higher protein"),
    "higher_fibre": ("dietary_fibre_g", "max", "higher fibre"),
}
COMPARE_KEYS = ["energy_kcal", "protein_g", "carbohydrate_g", "total_sugars_g", "total_fat_g", "saturated_fat_g", "dietary_fibre_g", "sodium_mg"]


def compare_products(products: list[dict], priorities: list[str], prefs: list[dict]) -> dict:
    cols = []
    for p in products:
        n = p["nutrition"]
        vals = {x["key"]: x["value"] for x in n["nutrients"]}
        allergen_text = " ".join(filter(None, [p.get("ingredients_text"), p.get("allergens_text")]))
        det = A.detect(p.get("ingredients_text"), allergen_text)
        cols.append({"id": p["id"], "name": p["name"], "brand": p["brand"], "category": p["category"],
                     "basis": n["basis"], "comparable": n["basis_known"],
                     "values": {k: (vals.get(k) if n["basis_known"] else None) for k in COMPARE_KEYS},
                     "values_as_stored": {k: vals.get(k) for k in COMPARE_KEYS} if not n["basis_known"] else None,
                     "ingredients_text": p.get("ingredients_text"), "additives": p.get("additive_codes", []),
                     "allergens_detected": [a["name"] for a in det["allergens"]],
                     "personal_alerts": A.match_prefs(det, prefs) if prefs else None,
                     "price": p.get("price")})
    rows = []
    for k in COMPARE_KEYS:
        known = [(c["values"][k], c["id"]) for c in cols if c["values"][k] is not None]
        lo = min(known)[0] if known else None
        hi = max(known)[0] if known else None
        rows.append({"key": k, "lowest": lo, "highest": hi, "missing_for": [c["id"] for c in cols if c["values"][k] is None]})
    findings = []
    for pr in priorities:
        key, direction, words = PRIORITIES[pr]
        known = [(c["values"][key], c) for c in cols if c["values"][key] is not None]
        if len(known) < 2:
            findings.append({"priority": pr, "text": f"Not enough per-100 g data to compare {words}.", "best": []})
            continue
        best_val = (min if direction == "min" else max)(v for v, _ in known)
        best = [c for v, c in known if v == best_val]
        others = [(v, c) for v, c in known if v != best_val]
        names = ", ".join(" ".join(filter(None, [c["brand"], c["name"]])) for c in best)
        text = f"For {words}: {names} ({best_val:g} per 100 g)"
        if others:
            worst_v = (max if direction == "min" else min)(v for v, _ in others)
            text += f" vs up to {worst_v:g} per 100 g for the others."
        missing = [c for c in cols if c["values"][key] is None]
        if missing:
            text += f" {len(missing)} product(s) could not be compared (missing or basis unknown)."
        findings.append({"priority": pr, "text": text, "best": [c["id"] for c in best]})
    return {"products": cols, "rows": rows, "findings": findings,
            "notes": ["Values are compared per 100 g, only when the dataset records them per 100 g.",
                      "No product is ranked 'healthiest' overall: the better choice depends on your priorities and portion size.",
                      "Price is shown only when the dataset contains it."]}


@router.get("/packaged/compare")
def compare(ids: str = Query(min_length=1, max_length=400), priorities: str = Query(""),
            data: PackagedFoodData = Depends(get_packaged_data), user: User | None = Depends(optional_user)):
    id_list = list(dict.fromkeys(i for i in ids.split(",") if i))
    if not 2 <= len(id_list) <= 4:
        return error("INVALID_SELECTION", "Choose between 2 and 4 products to compare.", 422)
    pr = [p for p in priorities.split(",") if p]
    bad = [p for p in pr if p not in PRIORITIES]
    if bad:
        return error("INVALID_PRIORITY", f"Unknown priority: {', '.join(bad)}.", 422)
    if not data.load():
        return error("DATASET_UNAVAILABLE", data.error or "Packaged-food data is unavailable.", 503)
    products = []
    for pid in id_list:
        rec = data.get(pid)
        if rec is None:
            return error("PRODUCT_NOT_FOUND", f"Product {pid} is not in the dataset.", 404)
        products.append(data.product_view(rec))
    prefs = []
    if user:
        conn = connect()
        try:
            from app.api.deps import user_allergens  # noqa: PLC0415
            prefs = user_allergens(conn, user.id)
        finally:
            conn.close()
    return {"success": True, **compare_products(products, pr, prefs), "priority_options": {k: v[2] for k, v in PRIORITIES.items()}}


@router.get("/packaged/compare/options")
def compare_options():
    return {"success": True, "priorities": {k: v[2] for k, v in PRIORITIES.items()}}
