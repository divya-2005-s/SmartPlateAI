"""Canonical nutrient keys and unit conversion, shared by the dashboard, comparison and reports.

Missing stays None. Values are only ever converted between compatible units (g <-> mg <-> µg, kJ -> kcal).
"""
from __future__ import annotations

import re

# key -> (label, unit, regex matched against a normalised source key or label)
CANONICAL: dict[str, tuple[str, str, str]] = {
    "energy_kcal": ("Energy", "kcal", r"^(energy|calor(ie|ies)|kcal)"),
    "protein_g": ("Protein", "g", r"^protein"),
    "carbohydrate_g": ("Carbohydrate", "g", r"^(total )?carbohydrate|^carbs?\b"),
    "total_sugars_g": ("Total sugars", "g", r"^(total )?sugars?( total)?( including nlea)?$|^sugars? total"),
    "added_sugars_g": ("Added sugars", "g", r"^added sugars?"),
    "dietary_fibre_g": ("Dietary fibre", "g", r"^(dietary )?fib(re|er)( total dietary)?"),
    "total_fat_g": ("Total fat", "g", r"^(total )?(fat|lipid)( total)?$|^total lipid|^fat total"),
    "saturated_fat_g": ("Saturated fat", "g", r"^(fatty acids total )?saturated|^sat(urated)? fat"),
    "trans_fat_g": ("Trans fat", "g", r"^(fatty acids total )?trans"),
    "cholesterol_mg": ("Cholesterol", "mg", r"^cholesterol"),
    "sodium_mg": ("Sodium", "mg", r"^sodium"),
    "potassium_mg": ("Potassium", "mg", r"^potassium"),
    "calcium_mg": ("Calcium", "mg", r"^calcium"),
    "iron_mg": ("Iron", "mg", r"^iron"),
    "vitamin_c_mg": ("Vitamin C", "mg", r"^vitamin c|^ascorbic"),
}
DASHBOARD_KEYS = ["energy_kcal", "protein_g", "carbohydrate_g", "total_fat_g", "dietary_fibre_g", "total_sugars_g", "sodium_mg"]
_FACTOR = {("g", "mg"): 1000.0, ("mg", "g"): 0.001, ("mg", "µg"): 1000.0, ("µg", "mg"): 0.001, ("g", "µg"): 1e6, ("µg", "g"): 1e-6,
           ("kj", "kcal"): 1 / 4.184}


def norm_unit(u: str | None) -> str | None:
    if not u:
        return None
    u = u.strip().lower()
    return {"ug": "µg", "mcg": "µg", "μg": "µg", "µg": "µg", "kcal": "kcal", "kj": "kj", "g": "g", "mg": "mg", "gm": "g"}.get(u, u)


def convert(value: float | None, from_unit: str | None, to_unit: str) -> float | None:
    if value is None:
        return None
    f, t = norm_unit(from_unit), norm_unit(to_unit)
    if f == t or f is None:
        return value
    factor = _FACTOR.get((f, t))
    return None if factor is None else value * factor


def canonical_key(key_or_label: str) -> str | None:
    s = re.sub(r"_(kcal|kj|mg|ug|mcg|g)$", "", key_or_label.strip().lower())
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    for key, (_, _, pat) in CANONICAL.items():
        if re.search(pat, s):
            return key
    return None


def unit_from_key(key: str) -> str | None:
    m = re.search(r"_(kcal|kj|mg|ug|mcg|g)$", key.lower())
    return norm_unit(m.group(1)) if m else None


def canonicalise(items: list[dict], value_field: str) -> dict[str, float | None]:
    """items: [{'key': 'protein_g', 'label': 'Protein', 'unit': 'g', value_field: 3.2}, ...] -> {'protein_g': 3.2, ...}.
    Keys not present at all are omitted; present-but-missing values stay None."""
    out: dict[str, float | None] = {}
    for it in items:
        ck = canonical_key(it.get("key") or "") or canonical_key(it.get("label") or "")
        if not ck or (ck in out and out[ck] is not None):
            continue
        out[ck] = convert(it.get(value_field), it.get("unit") or unit_from_key(it.get("key") or ""), CANONICAL[ck][1])
    return out


def scale(per100: dict[str, float | None], grams: float) -> dict[str, float | None]:
    return {k: (None if v is None else round(v * grams / 100.0, 4)) for k, v in per100.items()}


def labelled(values: dict[str, float | None]) -> list[dict]:
    return [{"key": k, "label": CANONICAL[k][0], "unit": CANONICAL[k][1], "value": values.get(k)} for k in CANONICAL if k in values]
