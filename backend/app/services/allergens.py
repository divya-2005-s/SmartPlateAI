"""Allergen detection from label text / ingredient lists, and comparison with a user's saved preferences.

Rules:
- An allergen is "declared" when an allergen statement (e.g. "Contains: milk") names it, "in ingredients" when an
  ingredient synonym matches, and "may contain" when only a precautionary statement names it.
- Missing information is never treated as "allergen-free": if no ingredients were read, the result says incomplete.
- Image analysis cannot detect traces or cross-contamination; only what is written on the label (or in a database).
"""
from __future__ import annotations

import re

# key -> (display name, synonym regex). Synonyms cover common Indian / international label wording.
ALLERGENS: dict[str, tuple[str, str]] = {
    "milk": ("Milk", r"milk|dairy|lactose|whey|casein(ate)?|butter(milk)?|cheese|curd|yogh?urt|ghee|paneer|cream|khoa|khoya|milk\s*solids"),
    "egg": ("Egg", r"\beggs?\b|albumin|ovalbumin|egg\s*powder|mayonnaise"),
    "peanut": ("Peanut", r"peanuts?|groundnuts?|arachis"),
    "tree_nuts": ("Tree nuts", r"almonds?|cashews?|walnuts?|pistachios?|hazelnuts?|pecans?|macadamia|brazil\s*nuts?|tree\s*nuts?|badam|kaju|akhrot"),
    "soy": ("Soy", r"\bsoy(a|abean|beans)?\b|soy\s*lecithin|tofu|edamame"),
    "wheat_gluten": ("Wheat / gluten", r"wheat|gluten|maida|atta|semolina|sooji|suji|rava|barley|\brye\b|spelt|malt"),
    "fish": ("Fish", r"\bfish\b|anchov(y|ies)|tuna|salmon|sardines?|cod\b|fish\s*sauce"),
    "crustaceans": ("Crustaceans", r"crustaceans?|shrimps?|prawns?|crabs?|lobsters?"),
    "molluscs": ("Molluscs", r"molluscs?|mollusks?|squid|octopus|clams?|mussels?|oysters?|scallops?"),
    "sesame": ("Sesame", r"sesame|\btil\b|gingelly|tahini"),
    "mustard": ("Mustard", r"mustard|rai\b|sarson"),
    "celery": ("Celery", r"celery|celeriac"),
    "lupin": ("Lupin", r"lupin|lupine"),
    "sulphites": ("Sulphites", r"sulph?ites?|sulf?ites?|sulphur\s*dioxide|sulfur\s*dioxide|\b(ins|e)\s*-?\s*22[0-8]\b"),
}
# Old keys produced by the label parser, kept for backwards compatibility.
LEGACY_NAMES = {"milk": "milk", "egg": "egg", "peanut": "peanut", "tree_nuts": "tree nuts", "soy": "soy",
                "wheat_gluten": "wheat / gluten", "fish": "fish", "crustaceans": "crustacean / shellfish",
                "molluscs": "crustacean / shellfish", "sesame": "sesame", "mustard": "mustard", "sulphites": "sulphites",
                "celery": "celery", "lupin": "lupin"}
SEVERITIES = ("avoid", "severe")

_STATEMENT = re.compile(r"(allergen\w*\s*(information|advice|declaration)?\s*[:\-]?[^.\n]{0,200}|contains\s*[:\-]?[^.\n]{0,200})", re.I)
_TRACE = re.compile(r"(may\s+contain[^.\n]{0,200}|(produced|processed|manufactured|made|packed)\s+in\s+a\s+(facility|factory|plant|unit)[^.\n]{0,200}|traces?\s+of[^.\n]{0,160})", re.I)


def valid_key(key: str) -> bool:
    return key in ALLERGENS


def detect(ingredients_text: str | None, full_text: str | None = None, extra_declared: list[str] | None = None,
           extra_traces: list[str] | None = None) -> dict:
    """Return detected allergens with evidence. extra_* accept allergen keys from an external database (e.g. Open Food Facts)."""
    text = full_text or ""
    traces = [m.group(0) for m in _TRACE.finditer(text)]
    statements = [m.group(0) for m in _STATEMENT.finditer(text) if not re.match(r"\s*may", m.group(0), re.I)]
    found: dict[str, dict] = {}
    for key, (name, pat) in ALLERGENS.items():
        ev = []
        if any(re.search(pat, s, re.I) for s in statements):
            ev.append("allergen statement")
        if ingredients_text and re.search(pat, ingredients_text, re.I):
            ev.append("ingredient list")
        if extra_declared and key in extra_declared:
            ev.append("external database")
        trace = any(re.search(pat, s, re.I) for s in traces) or bool(extra_traces and key in extra_traces)
        if ev:
            found[key] = {"key": key, "name": name, "status": "contains", "evidence": ev, "also_may_contain": trace}
        elif trace:
            found[key] = {"key": key, "name": name, "status": "may_contain", "evidence": ["precautionary statement"],
                          "also_may_contain": True}
    complete = bool(ingredients_text and len(ingredients_text) > 10)
    return {"allergens": list(found.values()), "ingredients_read": complete,
            "note": None if complete else "No complete ingredient list was read, so allergens may be missing from this result."}


def match_prefs(detected: dict, prefs: list[dict]) -> dict:
    """Compare detection results with the user's preferences."""
    by_key = {a["key"]: a for a in detected["allergens"]}
    confirmed, possible = [], []
    for p in prefs:
        a = by_key.get(p["allergen"])
        if not a:
            continue
        item = {"allergen": p["allergen"], "name": a["name"], "severity": p.get("severity", "avoid"), "evidence": a["evidence"]}
        (confirmed if a["status"] == "contains" else possible).append(item)
    warnings = []
    if not detected["ingredients_read"]:
        warnings.append("Incomplete label: no full ingredient list was read. This does not mean the product is free of your allergens.")
    if prefs and not confirmed and not possible and detected["ingredients_read"]:
        warnings.append("None of your saved allergens were found in the text that was read. Always check the physical label; "
                        "image analysis cannot detect traces or cross-contamination.")
    return {"confirmed": confirmed, "possible": possible, "warnings": warnings, "preferences_checked": [p["allergen"] for p in prefs]}


def ingredients_conflicts(ingredients: list[str], prefs: list[dict]) -> list[dict]:
    """Used for meal plans: which saved allergens match any listed ingredient name."""
    out = []
    joined = " | ".join(ingredients)
    for p in prefs:
        entry = ALLERGENS.get(p["allergen"])
        if entry and re.search(entry[1], joined, re.I):
            hits = [i for i in ingredients if re.search(entry[1], i, re.I)]
            out.append({"allergen": p["allergen"], "name": entry[0], "severity": p.get("severity", "avoid"), "ingredients": hits})
    return out


def legacy_list(ingredients_text: str | None, full_text: str) -> list[dict]:
    """Output shape used by label_parser.parse_label (kept stable for the existing UI and tests)."""
    res = detect(ingredients_text, full_text)
    out, seen = [], set()
    for a in res["allergens"]:
        name = LEGACY_NAMES.get(a["key"], a["name"].lower())
        if name in seen:
            continue
        seen.add(name)
        where = [e for e in a["evidence"] if e != "external database"]
        if a["status"] == "may_contain":
            where = ["allergen statement"]
        out.append({"allergen": name, "found_in": where, "may_contain_only": a["status"] == "may_contain", "key": a["key"]})
    return out
