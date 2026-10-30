"""Parse OCR text from a packaged-food label.

Everything returned here is read from the label text only. Nothing is inferred or invented: if a field
cannot be found it is returned as None / empty, and implausible numbers are flagged rather than "fixed".
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- helpers
_WS = re.compile(r"[ \t]+")
_NUM = r"(\d{1,5}(?:[.,]\d{1,3})?)"


def clean_text(text: str) -> str:
    text = text.replace("\r", "\n").replace("—", "-").replace("–", "-")
    lines = [_WS.sub(" ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


# ---------------------------------------------------------------- ingredients
_ING_START = re.compile(r"\bingred[i1l]ents?\b\s*[:;.\-]?", re.I)
_ING_STOP = re.compile(
    r"\bcontains\s*[:\-]|\b(nutrition(al)?\s+(information|facts|value)|nutrition|allergen|allergy|may\s+contain|best\s+before|"
    r"use\s+by|mfd|mfg|manufactured|marketed|packed\s+(by|on)|storage|store\s+in|net\s+(wt|weight|qty|quantity)|"
    r"directions|batch|fssai|lic\.?\s*no|customer\s+care|mrp|per\s+100)\b",
    re.I,
)


def extract_ingredients(text: str) -> tuple[str | None, list[str]]:
    m = _ING_START.search(text)
    if not m:
        return None, []
    rest = text[m.end():]
    stop = _ING_STOP.search(rest)
    section = rest[: stop.start()] if stop else rest[:700]
    section = " ".join(section.split()).strip(" .,:;")
    if len(section) < 3:
        return None, []
    items, depth, cur = [], 0, []
    for ch in section:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in ",;" and depth == 0:
            items.append("".join(cur).strip(" .")); cur = []
        else:
            cur.append(ch)
    items.append("".join(cur).strip(" ."))
    return section, [i for i in items if len(i) >= 2][:60]


# ---------------------------------------------------------------- additive (INS / E) codes
_ROMAN = r"(?:\s*\(?\s*(i{1,3}|iv|v|vi{0,3}|ix|x)\s*\)?)?"
_PREFIXED = re.compile(r"\b(?:INS|E)\s*[-.:]?\s*(\d{3,4})([a-f])?" + _ROMAN + r"(?![\d])", re.I)
_PAREN = re.compile(r"\(\s*(\d{3,4})([a-f])?" + _ROMAN + r"\s*[),]", re.I)


def normalise_code(num: str, letter: str | None = None, roman: str | None = None) -> str | None:
    n = int(num)
    if not 100 <= n <= 1521:  # INS numbers fall in this range; anything else is not an additive code
        return None
    code = f"{n}{(letter or '').lower()}"
    return f"{code}({roman.lower()})" if roman else code


def extract_additive_codes(text: str, ingredients_section: str | None) -> list[str]:
    """INS/E codes with an explicit INS/E prefix anywhere, plus bare (322)-style codes inside the ingredients section only."""
    found: list[str] = []
    for m in _PREFIXED.finditer(text):
        c = normalise_code(m.group(1), m.group(2), m.group(3))
        if c and c not in found:
            found.append(c)
    if ingredients_section:
        for m in _PAREN.finditer(ingredients_section):
            c = normalise_code(m.group(1), m.group(2), m.group(3))
            if c and c not in found:
                found.append(c)
    return found


def base_code(code: str) -> str:
    """'500(ii)' -> '500', '150d' -> '150d'."""
    return code.split("(")[0]


# ---------------------------------------------------------------- nutrition table
NUTRIENTS = [
    # key, label, regex for the name, default unit, plausible max per 100 g
    ("energy_kcal", "Energy", r"energy|calories|calorie", "kcal", 900.0),
    ("protein_g", "Protein", r"protein", "g", 100.0),
    ("carbohydrate_g", "Carbohydrate", r"(total\s+)?carbohydrates?|carbs?", "g", 100.0),
    ("total_sugars_g", "Total sugars", r"(total\s+)?sugars?", "g", 100.0),
    ("added_sugars_g", "Added sugars", r"added\s+sugars?", "g", 100.0),
    ("dietary_fibre_g", "Dietary fibre", r"(dietary\s+)?fib(re|er)", "g", 100.0),
    ("total_fat_g", "Total fat", r"(total\s+)?fat", "g", 100.0),
    ("saturated_fat_g", "Saturated fat", r"saturate[sd](\s+fat(ty\s+acids)?)?|sat\.?\s*fat", "g", 100.0),
    ("trans_fat_g", "Trans fat", r"trans(\s+fat(ty\s+acids)?)?", "g", 100.0),
    ("cholesterol_mg", "Cholesterol", r"cholesterol", "mg", 3000.0),
    ("sodium_mg", "Sodium", r"sodium", "mg", 40000.0),
    ("calcium_mg", "Calcium", r"calcium", "mg", 5000.0),
    ("iron_mg", "Iron", r"iron", "mg", 500.0),
]
_ORDER_SPECIFIC_FIRST = ["added_sugars_g", "saturated_fat_g", "trans_fat_g"]  # match before generic sugar / fat
_NEXT_NAME = re.compile(r"\b(" + "|".join(n[2] for n in NUTRIENTS) + r")\b", re.I)
_UNIT = re.compile(r"^\s*(kcal|kj|mg|mcg|µg|ug|g)\b", re.I)


_P100 = re.compile(r"per\s*100\s*(g|gm|ml)|100\s*(g|gm|ml)\s*(provides|contains)?")
_PSERVE = re.compile(r"per\s*(serve|serving|portion|pack)")


def _detect_basis(text: str) -> str:
    """Which column the values were read from. With both a per-100 and a per-serving heading, their order is taken only from a
    line that shows both (the column header row); a per-serving phrase elsewhere ("Amount per serving" titles, "% RDA per
    serve" columns) says nothing about the first column, so the basis is then 'unknown' rather than guessed."""
    low = text.lower()
    p100, pserve = _P100.search(low), _PSERVE.search(low)
    if p100 and pserve:
        for line in low.split("\n"):
            a, b = _P100.search(line), _PSERVE.search(line)
            if a and b:
                return "per 100 g" if a.start() < b.start() else "per serving"
        return "unknown"
    if p100:
        return "per 100 g"
    if pserve:
        return "per serving"
    return "unknown"


# A unit-less gram value with two decimals ending in 9 is usually OCR reading "15.8g" as "15.89": too uncertain to show.
_G_AS_9 = re.compile(r"^\d{1,3}[.,]\d9$")


def extract_serving_size(text: str) -> float | None:
    m = re.search(r"serv(?:ing|e)\s*(?:size)?\s*[:(\-]?\s*" + _NUM + r"\s*(g|gm|ml)\b", text, re.I)
    v = _to_float(m.group(1)) if m else None
    return v if v and 0 < v <= 2000 else None


_NUT_HEADER = re.compile(r"nutrition(al)?\s*(information|facts|value|info)?|per\s*100\s*(g|gm|ml)|amount\s+per", re.I)


def _nutrition_lines(text: str) -> list[str]:
    """Lines of the nutrition panel: everything after its header if one is found; never the ingredient list."""
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if _NUT_HEADER.search(ln) and not _ING_START.search(ln)), None)
    if start is not None:
        out = []
        for ln in lines[start:]:
            if _ING_START.search(ln):  # an ingredients list after the table ("SUGAR, ACIDITY REGULATORS (330 ...") is not nutrition
                break
            out.append(ln)
        return out
    section, _ = extract_ingredients(text)
    if not section:
        return lines
    ing_words = set(section.lower().split())
    # drop lines that are mostly ingredient-list words
    return [ln for ln in lines if not ln.strip() or sum(w in ing_words for w in ln.lower().split()) < 0.6 * len(ln.split())]


def extract_nutrition(text: str) -> dict:
    basis = _detect_basis(text)
    order = sorted(NUTRIENTS, key=lambda n: 0 if n[0] in _ORDER_SPECIFIC_FIRST else 1)
    values: dict[str, dict] = {}
    unreadable: list[dict] = []
    for line in _nutrition_lines(text):
        low = line.lower()
        for key, label, pat, unit, vmax in order:
            if key in values:
                continue
            m = re.search(r"\b(" + pat + r")\b", low)
            if not m:
                continue
            if key == "total_sugars_g" and "added" in low:
                continue
            if key == "total_fat_g" and re.search(r"saturate[sd]|trans|mono|poly", low):
                continue
            tail = line[m.end():]
            tail_low = tail.lower()
            unit_before = None
            hdr = re.match(r"\s*\(?\s*(kcal|kj|mg|mcg|µg|ug|g)\s*\)?", tail_low)
            if hdr:  # e.g. "Energy (kcal) 512"
                unit_before = hdr.group(1)
                tail = tail[hdr.end():]
            nm = re.search(r"(?<![A-Za-z0-9.,])" + _NUM, tail)  # not part of "B3" / "B12" / "E330"
            if not nm or nm.start() > 25:  # the value must follow the nutrient name closely
                continue
            between = tail[:nm.start()]
            if _NEXT_NAME.search(between):  # "TRANS FAT: iM PROTEIN: 0g": the number belongs to the next nutrient
                continue
            if ":" in re.sub(r"^\s*[:(\-]?", "", between, count=1):  # "SODIUM: Sy bay B3: 1.9mg": another "label:" comes first
                continue
            if re.match(r"\s*%", tail[nm.end():]):  # a percentage (ingredient share or % RDA), not an amount
                continue
            val = _to_float(nm.group(1))
            if val is None:
                continue
            um = _UNIT.match(tail[nm.end():])
            found_unit = (um.group(1) if um else unit_before or "").lower()
            if unit == "g" and not found_unit and _G_AS_9.match(nm.group(1)):
                unreadable.append({"key": key, "label": label, "raw": line.strip()[:120],
                                   "reason": "the unit 'g' may have been read as the digit 9"})
                break
            entry = {"label": label, "value": val, "unit": unit, "raw": line.strip()[:120], "flags": []}
            if key == "energy_kcal":
                if found_unit == "kj":
                    entry.update(value=round(val / 4.184, 1), raw_value=val, raw_unit="kJ")
                    entry["flags"].append("converted from kJ")
            elif found_unit in ("mg",) and unit == "g":
                entry["value"] = round(val / 1000, 4)
                entry["flags"].append("converted from mg")
            elif found_unit == "g" and unit == "mg":
                entry["value"] = round(val * 1000, 2)
                entry["flags"].append("converted from g")
            elif found_unit in ("mcg", "µg", "ug") and unit == "mg":
                entry["value"] = round(val / 1000, 4)
                entry["flags"].append("converted from µg")
            if basis == "per 100 g" and entry["value"] > vmax:  # physically impossible per 100 g: not shown
                unreadable.append({"key": key, "label": label, "raw": line.strip()[:120],
                                   "reason": f"{entry['value']:g} {unit} per 100 g is not possible"})
                continue
            values[key] = entry  # several nutrients can share one line ("ENERGY: 28kcal, TOTAL CARBOHYDRATE: 7g, ...")
    notes = []
    serving = extract_serving_size(text)
    if basis == "per serving" and serving:
        too_big = [v["label"] for v in values.values() if v["unit"] == "g" and v["value"] > serving * 1.02]
        if too_big:  # physically impossible per serving: the values come from another column (usually per 100 g)
            notes.append(f"{', '.join(too_big)} exceed the {serving:g} g serving size, so these values cannot be per serving; "
                         "the column could not be determined. Check the pack.")
    if basis == "per serving" and _per_serve_only_in_serving_size_line(text):
        notes.append("The only 'per serving' heading read is part of the serving-size line, so which column these values come "
                     "from is not certain (a 'per 100 g' heading may not have been read). Check the pack.")
    if notes:
        basis = "unknown"
    return {"basis": basis, "values": values, "source": "package label (OCR)", "unreadable": unreadable,
            "basis_note": " ".join(notes) or None}


def _per_serve_only_in_serving_size_line(text: str) -> bool:
    """'SERVE SIZE: 15 g | AMOUNT PER 100 g | PER SERVE' read as 'SERVE SIZE: 15 g PER SERVE': the per-serving phrase is a
    column heading merged into the serving-size line, not evidence that the first value column is per serving."""
    lines = [ln for ln in text.lower().split("\n") if _PSERVE.search(ln)]
    return bool(lines) and all(re.search(r"serv(e|ing)s?\s*size", ln) for ln in lines)


# ---------------------------------------------------------------- allergens & identifiers


def extract_allergens(text: str, ingredients_section: str | None) -> list[dict]:
    """Only reports allergens named in an allergen statement or in the ingredient list read from the label."""
    from app.services.allergens import legacy_list  # noqa: PLC0415
    return legacy_list(ingredients_section, text)


# ---------------------------------------------------------------- dates, storage, additive classes, name candidate
_DATE = r"(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}|\d{1,2}[./\-]\d{4}|\d{1,2}\s*[A-Za-z]{3,9}\.?\s*\d{2,4}|[A-Za-z]{3,9}\.?\s*\d{4})"
_DATE_KINDS = [
    ("manufactured", r"(mfd|mfg|manufactured|date\s+of\s+(mfg|manufacture)|packed\s+on|pkd|pkg\.?\s*date|date\s+of\s+packing)"),
    ("expiry", r"(exp(iry)?(\s+date)?|use\s+by|best\s+before(\s+date)?|bb)"),
]


def extract_dates(text: str) -> list[dict]:
    """Dates exactly as printed. They are never inferred or converted, because label formats are ambiguous."""
    out = []
    for kind, pat in _DATE_KINDS:
        for m in re.finditer(pat + r"\W{0,6}" + _DATE, text, re.I):
            out.append({"type": kind, "as_printed": m.group(m.lastindex).strip(), "context": m.group(0)[:60]})
        rel = re.search(r"best\s+before\s+(\d{1,2})\s*(months?|days?|weeks?)\s+from\s+(the\s+date\s+of\s+)?(manufacture|mfg|packing|packaging)", text, re.I)
        if kind == "expiry" and rel:
            out.append({"type": "expiry_relative", "as_printed": rel.group(0), "context": rel.group(0)[:80]})
    seen, uniq = set(), []
    for d in out:
        k = (d["type"], d["as_printed"].lower())
        if k not in seen:
            seen.add(k)
            uniq.append(d)
    return uniq[:6]


def extract_storage(text: str) -> list[str]:
    found = []
    for m in re.finditer(r"((store|keep)\s[^.\n]{3,140}|refrigerate[^.\n]{0,120}|once\s+opened[^.\n]{0,140}|consume\s+within[^.\n]{0,80})", text, re.I):
        t = " ".join(m.group(0).split())
        if t.lower() not in (f.lower() for f in found):
            found.append(t)
    return found[:4]


_CLASS_WORDS = r"(preservatives?|colou?rs?|colou?ring|sweeteners?|artificial\s+sweeteners?|emulsifiers?|stabili[sz]ers?|thickeners?|" \
               r"antioxidants?|acidity\s+regulators?|flavou?r\s+enhancers?|raising\s+agents?|anti-?caking\s+agents?|humectants?|" \
               r"glazing\s+agents?|thickening\s+agents?|firming\s+agents?|bleaching\s+agents?)"


def extract_additive_classes(text: str) -> list[dict]:
    """'Preservative (INS 211)' -> {'function': 'preservative', 'codes': ['211']} as declared on the label."""
    out = []
    for m in re.finditer(_CLASS_WORDS + r"\s*[:\-]?\s*\(([^)]{1,80})\)", text, re.I):
        codes = extract_additive_codes("(" + m.group(2) + ")", "(" + m.group(2) + ",")
        fn = re.sub(r"\s+", " ", m.group(1).lower()).rstrip("s") if not m.group(1).lower().endswith("ss") else m.group(1).lower()
        out.append({"function": fn, "codes": codes, "as_printed": m.group(0)[:100]})
    return out


def product_name_candidate(text: str) -> str | None:
    skip = re.compile(r"ingred|nutrition|energy|protein|net\s|mrp|fssai|best|mfd|mfg|exp|store|per\s|serving|contains|allergen|www|@|\d{4,}", re.I)
    for line in text.split("\n")[:8]:
        words = re.findall(r"[A-Za-z]{2,}", line)
        if 2 <= len(words) <= 8 and not skip.search(line) and len("".join(words)) >= 6:
            return " ".join(line.split())[:80]
    return None


def _gs1_ok(code: str) -> bool:
    d = [int(c) for c in code]
    return (10 - sum(x * (3 if i % 2 == 0 else 1) for i, x in enumerate(reversed(d[:-1]))) % 10) % 10 == d[-1]


def _barcode_in_text(text: str, fssai: str | None) -> str | None:
    """Barcode digits printed under the bars. They are usually printed in groups ("8 901058 851380" for EAN-13,
    "0 36000 29145 2" for UPC-A), so spaces and hyphens between the groups are allowed. Only digit strings with a
    valid GS1 check digit are accepted, which filters out most phone numbers, batch codes and licence numbers."""
    patterns = (r"(?<![\d])(\d)[ \-]?(\d{6})[ \-]?(\d{6})(?![\d])",             # EAN-13
                r"(?<![\d])(\d)[ \-]?(\d{5})[ \-]?(\d{5})[ \-]?(\d)(?![\d])")  # UPC-A
    # 8-digit EAN-8 codes are not read from text: dates and batch numbers pass the check digit too often.
    for pat in patterns:
        for m in re.finditer(pat, text):
            code = "".join(m.groups())
            if fssai and code in fssai:
                continue
            if _gs1_ok(code) and len(set(code)) > 2:
                return code
    return None


def extract_identifiers(text: str) -> dict:
    fssai = re.search(r"(?:fssai|lic(?:\.|ence|ense)?\s*no)\D{0,15}(\d{14})", text, re.I)
    ean = _barcode_in_text(text, fssai.group(1) if fssai else None)
    net = re.search(r"net\s*(?:wt|weight|qty|quantity)?\.?\s*[:\-]?\s*" + _NUM + r"\s*(kg|g|gm|ml|l)\b", text, re.I)
    return {
        "fssai_licence": fssai.group(1) if fssai else None,
        "barcode_digits": ean,
        "net_quantity": f"{net.group(1)} {net.group(2)}" if net else None,
    }


def parse_label(text: str) -> dict:
    text = clean_text(text)
    section, items = extract_ingredients(text)
    return {
        "ingredients_text": section,
        "ingredients": items,
        "additive_codes": extract_additive_codes(text, section),
        "nutrition": extract_nutrition(text),
        "serving_size_g": extract_serving_size(text),
        "allergens": extract_allergens(text, section),
        "dates": extract_dates(text),
        "storage": extract_storage(text),
        "additive_classes": extract_additive_classes(text),
        "product_name_candidate": product_name_candidate(text),
        "identifiers": extract_identifiers(text),
    }
