"""USDA FoodData Central search for foods outside the project's nutrition CSV (e.g. "red onion").

A match is accepted only when ALL of these hold, otherwise nutrition is reported as unavailable:
  - the record is Foundation or SR Legacy data (laboratory/reference data, not branded products);
  - every main word of the identified food appears in the record description (plural-insensitive);
  - for fruits and vegetables, the record is described as raw (a cooked or processed record is not substituted).
Values are per 100 g of the reference sample. Needs USDA_FDC_API_KEY (free); results cached for 30 days.
"""
from __future__ import annotations

import logging
import re
import urllib.parse

from app.core.config import get_settings
from app.services.http import ExternalError, cache_get, cache_key, cache_set, request_json

log = logging.getLogger("smartplate.usda")
SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
TTL = 30 * 24 * 3600
STOP = {"fresh", "whole", "raw", "ripe", "the", "a", "an", "of", "and", "with", "sliced", "chopped", "cut", "piece", "pieces", "small", "large"}
PROCESSED = re.compile(r"\b(cooked|boiled|fried|canned|frozen|dehydrated|dried|baked|roasted|pickled|juice|sauce|soup|powder)\b", re.I)
# FDC nutrient name -> (key, label, unit)
FDC_MAP = [
    (r"^Energy$|^Energy \(Atwater (General|Specific) Factors\)$", "energy_kcal", "Energy", "kcal"),
    (r"^Protein$", "protein_g", "Protein", "g"),
    (r"^Carbohydrate, by difference$|^Carbohydrate, by summation$", "carbohydrate_g", "Carbohydrate", "g"),
    (r"^Total lipid \(fat\)$", "total_fat_g", "Total fat", "g"),
    (r"^Fatty acids, total saturated$", "saturated_fat_g", "Saturated fat", "g"),
    (r"^Fiber, total dietary$", "dietary_fibre_g", "Dietary fibre", "g"),
    (r"^Sugars, total including NLEA$|^Total Sugars$|^Sugars, Total$", "total_sugars_g", "Total sugars", "g"),
    (r"^Sodium, Na$", "sodium_mg", "Sodium", "mg"),
    (r"^Potassium, K$", "potassium_mg", "Potassium", "mg"),
    (r"^Calcium, Ca$", "calcium_mg", "Calcium", "mg"),
    (r"^Iron, Fe$", "iron_mg", "Iron", "mg"),
    (r"^Vitamin C, total ascorbic acid$", "vitamin_c_mg", "Vitamin C", "mg"),
]
NOTE = ("Reference values for this type of food from USDA FoodData Central, not measurements of the photographed item. "
        "Real nutrition depends on variety, portion size and preparation.")


def enabled() -> bool:
    return bool(get_settings().usda_fdc_api_key.strip())


def _stem(w: str) -> str:
    w = w.lower()
    for suf in ("ies", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def _words(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-zA-Z]+", text.lower()) if w not in STOP and len(w) >= 3]


DATA_TYPES = ("Foundation", "SR Legacy", "Survey (FNDDS)")
DTYPE_RANK = {"Foundation": 0.0, "SR Legacy": 0.01, "Survey (FNDDS)": 0.02}  # tie-break only: lab analysis before recipe-based
# A leading USDA term that names a food group ("Cheese, paneer", "Bread, chapati or roti") rather than a product that merely
# contains the food ("Crackers, milk", "Bagels, egg").
GROUP_HEADS = {_stem(w) for w in ("cheese", "bread", "milk", "yogurt", "rice", "beans", "cereals", "egg", "fish", "beverages", "soup")}
# Words that do not make a record a different food (generic / grade / packaging-neutral descriptors).
NEUTRAL = {_stem(w) for w in ("nfs", "ns", "plain", "whole", "raw", "grade", "large", "medium", "regular", "commercially",
                              "prepared", "fruit", "type", "not", "further", "specified")}
# Regional names -> the USDA vocabulary for the same food (used only to build the nutrition query, never for recognition).
SYNONYMS = {"curd": "yogurt", "dahi": "yogurt", "daal": "dal", "dhal": "dal", "chappati": "chapati", "phulka": "chapati"}
MAX_PENALTY = 1.0  # a record with a modifier that changes the food ("Coconut milk" for milk) scores >= 1 and is never used
# Dishes/accompaniments that make a record a different food when the identified food does not name them
# ("Taco or tostada salad with chicken" is not a chicken taco; "Frankfurters or hot dogs and sauerkraut" is not a frankfurter).
DISHES = {_stem(w) for w in ("salad", "soup", "stew", "casserole", "sauce", "gravy", "sauerkraut", "rice", "noodles", "pasta", "spaghetti",
                              "pie", "burrito", "sandwich", "pizza", "burger", "taco", "tostada", "wrap", "dumpling", "pilaf", "curry")}
# "with X" normally adds an ingredient that changes the food ("Pizza, cheese, with fruit"); these only describe the food itself.
WITH_OK = {_stem(w) for w in ("skin", "peel", "salt", "added")}


def query_name(food_name: str) -> str:
    return " ".join(SYNONYMS.get(w.lower(), w) for w in food_name.split())


def _same(want: str, tok: str) -> bool:
    return tok == want or (len(want) >= 4 and tok.startswith(want))  # "kiwifruit" is the kiwi


def match_penalty(description: str, data_type: str, food_name: str, produce: bool) -> float | None:
    found = match_score(description, data_type, food_name, produce)
    return None if found is None else found[0]


def match_score(description: str, data_type: str, food_name: str, produce: bool) -> tuple[float, bool] | None:
    """How far a record is from being exactly the identified food; None = not this food at all.
    0 = the record is the food itself (e.g. 'Milk, NFS' for milk); each extra word that changes the food in the record's
    leading term costs 1 ('Coconut milk'), other descriptive words 0.25 ('Cheese, Monterey'), a food-group prefix 0.5."""
    if not accept(description, data_type, food_name, produce):
        return None
    want = _words(food_name)
    head = want[-1]  # English head noun: "cooked white rice" -> rice
    wanted = lambda t: any(_same(w, t) for w in want)  # noqa: E731
    if any(t in DISHES and not wanted(t) for t in _words(description)):
        return None  # the record is (or comes with) a different dish
    added = [t for part in description.split(",") for m in [re.search(r"\bwith\b(.*)", part, re.I)] if m for t in _words(m.group(1))]
    base = _words(re.sub(r"\bwith\b[^,]*", " ", description, flags=re.I))
    if not any(_same(head, t) for t in base):
        return None  # the food only appears as an ingredient "with ..." of something else ("Rice, fried, with chicken")
    with_penalty = 0.0 if produce else 1.0 * sum(1 for t in added if not wanted(t) and t not in WITH_OK)
    segs, group = [], []  # words per alternative, and which comma-part each alternative belongs to
    for g, part in enumerate(description.split(",")):
        if re.match(r"\s*NS as to\b", part, re.I):
            continue  # "NS as to fat" = not specified: USDA's generic default, like NFS
        for alt in re.split(r"\bor\b", part):  # "chapati or roti" = alternative names of one food
            segs.append(_words(alt))
            group.append(g)
    pos = next((i for i, s in enumerate(segs) if any(_same(head, t) for t in s)), None)
    if pos is None:
        return None
    if group[pos] > 0 and (head in GROUP_HEADS or not (segs[0] and all(t in GROUP_HEADS for t in segs[0]))):
        # The food is only an ingredient/flavour of another product ("Crackers, milk"), or it is itself a food group, so a
        # group prefix names a different food ("Bread, rice" is rice bread; "Cheese, paneer" is paneer).
        return None
    known = lambda t: t in NEUTRAL or any(_same(w, t) for w in want)  # noqa: E731
    extra_head = [t for t in segs[pos] if not known(t)]
    skip = {i for i in range(len(segs)) if group[i] == group[pos] or (group[pos] > 0 and group[i] == 0)}  # synonyms, group prefix
    others = [t for i, s in enumerate(segs) if i not in skip for t in s if not known(t)]
    penalty = (len(extra_head) * 1.0 + (0.5 if group[pos] > 0 else 0.0) + 0.25 * len(others) + with_penalty
               + DTYPE_RANK.get(data_type, 0.05))
    # generic = the record is the food itself: only a food-group prefix ('Cheese, paneer') and neutral words besides it
    return penalty, not extra_head and not others


def accept(description: str, data_type: str, food_name: str, produce: bool) -> bool:
    if data_type not in DATA_TYPES:
        return False
    want = _words(food_name)
    have = set(_words(description))
    if not want or not all(w in have for w in want):
        return False
    if produce and (PROCESSED.search(description) or not re.search(r"\braw\b", description, re.I)):
        return False
    return True


def _nutrients(food: dict) -> dict[str, tuple[float, str]]:
    out: dict[str, tuple[float, str]] = {}
    for n in food.get("foodNutrients") or []:
        name, unit, val = n.get("nutrientName", ""), (n.get("unitName") or "").upper(), n.get("value")
        if not isinstance(val, (int, float)):
            continue
        for pat, key, _label, want_unit in FDC_MAP:
            if key in out or not re.search(pat, name):
                continue
            if key == "energy_kcal" and unit != "KCAL":
                continue
            if want_unit == "mg" and unit == "G":
                val = val * 1000
            elif want_unit == "g" and unit == "MG":
                val = val / 1000
            out[key] = (float(val), want_unit)
    return out


def lookup(food_name: str, category: str, serving_grams: float | None = None) -> dict:
    """Returns {'status': 'found', 'nutrition': {...same shape as NutritionReference.lookup...}} or
    {'status': 'unavailable'|'no_match', 'message': ...}. Never substitutes another food's values."""
    if not enabled():
        return {"status": "unavailable", "message": "Verified nutrition for foods outside the 24 model classes needs USDA_FDC_API_KEY on the server."}
    produce = category in ("Fruits", "Vegetables")
    name = query_name(food_name)
    query = name + (" raw" if produce else "")
    key = cache_key("fdc-search-v2", query.lower())
    data = cache_get(key)
    if data is None:
        try:
            data = request_json(SEARCH_URL + "?" + urllib.parse.urlencode({"api_key": get_settings().usda_fdc_api_key.strip()}),
                                method="POST", payload={"query": query, "dataType": list(DATA_TYPES), "pageSize": 50})
        except ExternalError as exc:
            log.info("FDC search failed: %s", exc.code)  # URL contains the key; never logged
            return {"status": "unavailable", "message": f"USDA FoodData Central could not be reached ({exc.code})."}
        cache_set(key, data, TTL)
    # Rank every candidate instead of taking the first one that merely contains the word (which returned
    # "Crackers, milk" for milk and "Rice crackers" for rice).
    ranked = []
    for i, food in enumerate((data.get("foods") or [])[:50]):
        desc, dtype = food.get("description", ""), food.get("dataType", "")
        found = match_score(desc, dtype, name, produce)
        if found is None or found[0] >= MAX_PENALTY:
            continue
        penalty, generic = found
        values = _nutrients(food)
        if "energy_kcal" not in values and "protein_g" not in values:
            continue
        ranked.append((penalty, not ("nfs" in _words(desc)), i, food, values, generic))
    if not ranked:
        return {"status": "no_match", "message": f"No verified USDA reference record clearly matches '{food_name}', so nutrition is not shown."}
    generics = sorted(r for r in ranked if r[5])  # the food itself; an explicit 'NFS' (not further specified) record first
    ranked.sort(key=lambda r: (r[0], r[2]))
    if generics:
        best = generics[0]
    else:
        best = ranked[0]
        rivals = [r for r in ranked[1:] if r[0] - best[0] < 0.05 and r[3].get("description", "").casefold() != best[3].get("description", "").casefold()]
        if rivals:  # e.g. "Cheese": Monterey vs paneer vs mozzarella differ a lot; do not pick one at random
            names = "; ".join(r[3].get("description", "") for r in [best, *rivals][:3])
            return {"status": "no_match", "ambiguous": True,
                    "message": f"Several different USDA records match '{food_name}' ({names}), and their nutrition differs, so none is "
                               "shown. Correct the food name to the specific type."}
    _p, _nfs, _i, food, values, _g = best
    desc, dtype = food.get("description", ""), food.get("dataType", "")
    items, missing = [], []
    for _pat, k, label, unit in FDC_MAP:
        v = values.get(k, (None, unit))[0]
        if v is None:
            missing.append(label)
        items.append({"key": k, "label": label, "unit": unit, "per_100g": None if v is None else round(v, 3),
                      "per_serving": None if (v is None or serving_grams is None) else round(v * serving_grams / 100.0, 3)})
    fdc_id = food.get("fdcId")
    note = NOTE + (" This record is from USDA's survey database (FNDDS): values for a prepared dish are based on a standard "
                   "recipe, and home recipes differ." if dtype == "Survey (FNDDS)" else "")
    return {"status": "found", "nutrition": {
        "basis": f"per 100 g by weight (USDA FoodData Central {dtype}: {desc})", "source_fdc_id": fdc_id, "is_estimate": True,
        "note": note, "serving_grams": serving_grams, "matched_description": desc, "data_type": dtype,
        "matched_query": name if name != food_name else None,
        "source_url": f"https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients" if fdc_id else None,
        "serving_note": ("Scaled linearly from the per-100 g values using the serving size you entered." if serving_grams else
                         "No serving size was given, so only per-100 g values are shown."),
        "nutrients": items, "not_available": missing}}
