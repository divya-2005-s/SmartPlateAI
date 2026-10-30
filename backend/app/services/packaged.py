"""Packaged-food product records, additive reference data and OCR-text product matching.

Data comes only from the project's CSVs. Column names are detected from a list of common aliases so the loader
works with the cleaned CSVs; GET /api/packaged/status reports what was detected. Nothing is invented: a product
is reported as "matched" only when the label text gives strong evidence, otherwise candidates are offered for
the user to confirm, or the result is "unmatched".
"""
from __future__ import annotations

import difflib
import json
import math
import os
import re
import threading
import unicodedata
from pathlib import Path

import pandas as pd

from app.core.config import get_settings
from app.services.label_parser import base_code, normalise_code

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR_DEFAULT = Path(r"D:\Food_Composition_Project\output")

# ---------------------------------------------------------------- column aliases
PRODUCT_COLS = {
    "id": ["product_id", "id", "code", "barcode", "sku"],
    "name": ["product_name", "product", "name", "product_title", "item_name", "food_name", "title"],
    "brand": ["brand", "brands", "brand_name", "manufacturer"],
    "category": ["category", "categories", "food_category", "product_category", "type"],
    "ingredients": ["ingredients", "ingredients_text", "ingredient_list", "ingredient"],
    "additives": ["additives", "additive_codes", "ins_codes", "e_numbers", "additives_tags", "additives_list"],
    "serving": ["serving_size_g", "serving_size", "serving_g", "serving", "serving_quantity"],
    "allergens": ["allergens", "allergen_info", "allergen"],
    "price": ["price", "mrp", "price_inr", "mrp_inr", "price_rs"],
    "barcode": ["barcode", "ean", "ean13", "gtin", "upc", "code"],
    "quantity": ["quantity", "net_quantity", "net_weight", "pack_size", "net_wt", "size"],
}
NUTRIENT_COLS = [
    # key, label, unit, aliases (lower-case, exact match after normalisation)
    ("energy_kcal", "Energy", "kcal", ["energy_kcal", "energy_kcal_100g", "calories", "calories_kcal", "energy", "kcal"]),
    ("protein_g", "Protein", "g", ["protein_g", "protein", "proteins", "proteins_100g", "protein_100g"]),
    ("carbohydrate_g", "Carbohydrate", "g", ["carbohydrate_g", "carbohydrates_g", "carbohydrate", "carbohydrates", "carbs_g", "carbs", "carbohydrates_100g"]),
    ("total_sugars_g", "Total sugars", "g", ["sugar_g", "sugars_g", "total_sugars_g", "sugar", "sugars", "total_sugar_g", "sugars_100g"]),
    ("added_sugars_g", "Added sugars", "g", ["added_sugar_g", "added_sugars_g", "added_sugar", "added_sugars"]),
    ("dietary_fibre_g", "Dietary fibre", "g", ["fiber_g", "fibre_g", "dietary_fiber_g", "dietary_fibre_g", "fiber", "fibre", "fiber_100g"]),
    ("total_fat_g", "Total fat", "g", ["fat_g", "total_fat_g", "fat", "total_fat", "fat_100g"]),
    ("saturated_fat_g", "Saturated fat", "g", ["saturated_fat_g", "sat_fat_g", "saturated_fat", "saturated-fat_100g"]),
    ("trans_fat_g", "Trans fat", "g", ["trans_fat_g", "trans_fat"]),
    ("cholesterol_mg", "Cholesterol", "mg", ["cholesterol_mg", "cholesterol"]),
    ("sodium_mg", "Sodium", "mg", ["sodium_mg", "sodium"]),
    ("salt_g", "Salt", "g", ["salt_g", "salt"]),
    ("calcium_mg", "Calcium", "mg", ["calcium_mg", "calcium"]),
    ("iron_mg", "Iron", "mg", ["iron_mg", "iron"]),
]
# The dataset audit found ~85% of products store missing calcium / iron as 0, so 0 there means "not recorded".
ZERO_MEANS_MISSING = {"calcium_mg", "iron_mg"}
PLAUSIBLE_MAX_100G = {"energy_kcal": 900, "protein_g": 100, "carbohydrate_g": 100, "total_sugars_g": 100, "added_sugars_g": 100,
                      "dietary_fibre_g": 100, "total_fat_g": 100, "saturated_fat_g": 100, "trans_fat_g": 100,
                      "sodium_mg": 40000, "salt_g": 100}
ADD_COLS = {
    "code": ["ins_code", "code", "ins", "e_number", "additive_code", "ins_number", "e_code", "additive"],
    "name": ["additive_name", "name", "chemical_name", "common_name", "description"],
    "function": ["function", "functional_class", "category", "class", "purpose", "type", "technological_purpose"],
    "notes": ["notes", "regulatory_notes", "regulatory_status", "status", "remarks", "concern", "health_notes", "precautions", "safety_notes"],
    "product": ["product_name", "product", "product_id"],
}
GENERIC = set("""
the and with for from per pack packet net weight wt ingredients ingredient nutrition nutritional information facts value values
energy protein carbohydrate carbohydrates sugar sugars fat total saturated trans sodium fibre fiber calcium iron serving size
kcal mfd mfg date best before months store cool dry place india pvt ltd limited private company foods food products product
contains contain may allergen allergens added natural flavour flavours flavor flavors colour color edible vegetable oil salt
gms mrp incl all taxes veg new free original classic pure fresh premium approx serves made quality customer care email
""".split())
IDENTITY_WEAK = set("""
masala noodles noodle instant snack snacks chips chip biscuit biscuits cookie cookies namkeen mix mixture flavour flavor
flavoured classic spicy tangy tomato chocolate choco cream creamy juice drink tea coffee rice atta oil sauce ketchup soup
pasta oats cereal milk butter cheese sweet salted salt plain chilli chili pepper onion garlic lemon mango orange
""".split())
GENERIC_NAME_WORDS = {"noodles", "chips", "potato", "biscuit", "biscuits", "snack", "snacks", "oil", "flour",
                     "salt", "sugar", "rice", "wheat", "bread", "tea", "coffee", "milk"}
DISTINCTIVE_NAME_WORDS = {"maggi", "yippee", "nestle", "sunfeast", "masala", "minute", "chicken", "veg", "vegetable",
                         "classic", "family", "atta", "magic", "instant", "tasty", "peri", "sambar", "upma", "pasta"}
VARIANT_WORDS = {
    "masala", "chicken", "veg", "vegetable", "special", "korean", "bbq", "magic", "classic", "family", "atta",
    "cuppa", "instant", "minute", "vegetarian", "tasty", "cheese", "peri", "sambar", "upma", "pasta"
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


_QTY_TOKEN = re.compile(r"^\d+(?:g|gm|gms|kg|ml|l|ltr|pcs|n)$")


def tokens(s: str) -> list[str]:
    return [t for t in norm(s).split() if len(t) >= 3 and not t.isdigit() and not _QTY_TOKEN.match(t)]


# Characters OCR commonly confuses inside words (digit read for a letter). Applied only to tokens that are mostly letters.
_OCR_FOLD = str.maketrans({"0": "o", "1": "l", "5": "s", "8": "b", "6": "g", "2": "z", "4": "a", "7": "t", "3": "e", "9": "g"})


def fold(tok: str) -> str:
    letters = sum(c.isalpha() for c in tok)
    return tok.translate(_OCR_FOLD) if letters >= max(2, len(tok) - 2) else tok


def text_tokens(text: str) -> set[str]:
    """Tokens of label/OCR text, with OCR digit/letter confusions folded ("MAGG1" -> "maggl" is then fuzzy-matched)
    and hyphenated words also kept joined ("2-minute" -> "minute" and "2minute")."""
    out = set()
    for raw in re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()):
        low = raw.lower()
        parts = low.split("-")
        for t in parts + ["".join(parts)]:
            if len(t) >= 3 and not t.isdigit():
                out.add(fold(t))
    return out


def _edits(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similar(a: str, b: str) -> bool:
    """Spelling-tolerant equality for OCR output: 1 character error allowed in words of 5-7 letters, 2 in longer
    words, none in shorter words (so 'magic' is not taken for 'maggi')."""
    if a == b:
        return True
    n = min(len(a), len(b))
    if n < 5 or abs(len(a) - len(b)) > 1:
        return False
    return _edits(a, b) <= (1 if n <= 7 else 2)


_QTY = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|gm|gms|grams?|ml|l|ltr|litre|liter)\b", re.I)


def parse_quantity_g(text: str | None) -> float | None:
    """Pack size in grams (or ml) from text such as "70 g", "1 kg", "500ml"; None if absent."""
    if not text:
        return None
    m = _QTY.search(str(text))
    if not m:
        return None
    v, u = float(m.group(1)), m.group(2).lower()
    return v * 1000 if u in ("kg", "l", "ltr", "litre", "liter") else v


def _barcode_cell(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    d = re.sub(r"\D", "", str(v).split(".")[0] if re.fullmatch(r"\d+\.0", str(v)) else str(v))
    return d if len(d) in (8, 12, 13, 14) else None


def same_barcode(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.lstrip("0") == b.lstrip("0")


def _pick(cols: list[str], aliases: list[str]) -> str | None:
    lowered = {norm(c).replace(" ", "_"): c for c in cols}
    for a in aliases:
        if a in lowered:
            return lowered[a]
    return None


def _num(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        f = float(str(v).strip().replace(",", ""))
    except ValueError:
        m = re.match(r"\s*(\d+(?:\.\d+)?)", str(v))
        f = float(m.group(1)) if m else None
    return None if f is None or pd.isna(f) else f


def _codes_from_cell(v) -> list[str]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    out = []
    for m in re.finditer(r"(?:en:)?(?:e|ins)?\s*(\d{3,4})([a-f])?(?:\s*\(?\s*(i{1,3}|iv|v|vi{0,3}|ix|x)\s*\)?)?", str(v), re.I):
        c = normalise_code(m.group(1), m.group(2), m.group(3))
        if c and c not in out:
            out.append(c)
    return out


class PackagedFoodData:
    def __init__(self, products_csv: str | Path | None = None, additives_csv: str | Path | None = None,
                 reference_csv: str | Path | None = None) -> None:
        self._paths = (products_csv, additives_csv, reference_csv)
        self._lock = threading.Lock()
        self.loaded = False
        self.error: str | None = None
        self.products: list[dict] = []
        self.additive_info: dict[str, dict] = {}
        self.detected: dict = {}
        self._vocab: set[str] = set()
        self._idf: dict[str, float] = {}

    # ------------------------------------------------------------ path resolution
    def _resolve(self) -> tuple[Path | None, Path | None, Path | None]:
        s = get_settings()
        hints: dict = {}
        dp = BACKEND_DIR / "reports" / "dataset_paths.json"
        if dp.is_file():
            try:
                hints = json.loads(dp.read_text(encoding="utf-8"))
            except ValueError:
                hints = {}
        hint_vals = [str(v) for v in hints.values() if isinstance(v, str)]
        data_dir = Path(hints["food_csv"]).parent if isinstance(hints.get("food_csv"), str) else DATA_DIR_DEFAULT

        def find(explicit, env_val, hint_word, default_name, glob_pats):
            for cand in (explicit, env_val):
                if cand:
                    return Path(cand)
            for v in hint_vals:
                if hint_word(Path(v).name.lower()):
                    return Path(v)
            if (data_dir / default_name).is_file():
                return data_dir / default_name
            if data_dir.is_dir():
                for pat in glob_pats:
                    hits = sorted(data_dir.glob(pat))
                    if hits:
                        return hits[0]
            return None

        p = find(self._paths[0], s.packaged_foods_csv or os.environ.get("PACKAGED_FOODS_CSV"),
                 lambda n: "packaged" in n and "additive" not in n, "packaged_foods_india_clean.csv", ["packaged_foods*.csv"])
        a = find(self._paths[1], s.packaged_additives_csv or os.environ.get("PACKAGED_ADDITIVES_CSV"),
                 lambda n: "packaged" in n and "additive" in n, "packaged_food_additives.csv", ["packaged_food_additives*.csv"])
        r = find(self._paths[2], s.additive_reference_csv or os.environ.get("ADDITIVE_REFERENCE_CSV"),
                 lambda n: "additive" in n and ("ref" in n or "master" in n or "lookup" in n), "additive_reference.csv",
                 ["*additive*ref*.csv", "*ins*reference*.csv", "additives_reference*.csv"])
        return p, a, r

    # ------------------------------------------------------------ loading
    def load(self) -> bool:
        with self._lock:
            if self.loaded:
                return True
            p, a, r = self._resolve()
            if p is None or not p.is_file():
                self.error = "Packaged-food dataset was not found. Set PACKAGED_FOODS_CSV in backend/.env."
                return False
            df = pd.read_csv(p, low_memory=False, dtype=str)  # text: barcodes keep their leading zeros
            cols = list(df.columns)
            pc = {k: _pick(cols, v) for k, v in PRODUCT_COLS.items()}
            nc = {key: (_pick(cols, aliases), label, unit) for key, label, unit, aliases in NUTRIENT_COLS}
            if not pc["name"]:
                self.error = f"Could not find a product-name column in {p.name}. Columns: {', '.join(cols)}"
                return False
            self.detected = {"products_csv": str(p), "product_columns": {k: v for k, v in pc.items() if v},
                             "nutrient_columns": {k: v[0] for k, v in nc.items() if v[0]}, "rows": len(df)}
            for i, row in df.iterrows():
                name = str(row[pc["name"]]).strip()
                if not name or name.lower() == "nan":
                    continue
                brand = str(row[pc["brand"]]).strip() if pc["brand"] and pd.notna(row[pc["brand"]]) else None
                rec = {
                    "id": str(row[pc["id"]]) if pc["id"] and pd.notna(row[pc["id"]]) else str(i),
                    "name": name, "brand": brand,
                    "category": str(row[pc["category"]]) if pc["category"] and pd.notna(row[pc["category"]]) else None,
                    "ingredients_text": str(row[pc["ingredients"]]) if pc["ingredients"] and pd.notna(row[pc["ingredients"]]) else None,
                    "serving_size_g": _num(row[pc["serving"]]) if pc["serving"] else None,
                    "allergens_text": str(row[pc["allergens"]]) if pc["allergens"] and pd.notna(row[pc["allergens"]]) else None,
                    "price": _num(row[pc["price"]]) if pc["price"] else None,
                    "additive_codes": _codes_from_cell(row[pc["additives"]]) if pc["additives"] else [],
                    "nutrients_raw": {key: _num(row[col]) for key, (col, _, _) in nc.items() if col},
                    "barcode": _barcode_cell(row[pc["barcode"]]) if pc["barcode"] else None,
                    "quantity_g": parse_quantity_g(str(row[pc["quantity"]])) if pc["quantity"] and pd.notna(row[pc["quantity"]])
                    else parse_quantity_g(name),
                }
                brand_toks = set(tokens(brand or ""))
                rec["_name_toks"] = [t for t in dict.fromkeys(tokens(name)) if t not in GENERIC and t not in brand_toks]
                rec["_brand_toks"] = [t for t in dict.fromkeys(tokens(brand or "")) if t not in GENERIC]
                self.products.append(rec)
                self._vocab.update(rec["_name_toks"], rec["_brand_toks"])
            df_count: dict[str, int] = {}
            for rec in self.products:
                for t in set(rec["_name_toks"]) | set(rec["_brand_toks"]):
                    df_count[t] = df_count.get(t, 0) + 1
            n = max(1, len(self.products))
            self._idf = {t: math.log(1 + n / c) for t, c in df_count.items()}
            self._df = df_count
            self._load_additives(a, r)
            self.loaded = True
            return True

    def _load_additives(self, a: Path | None, r: Path | None) -> None:
        by_name = {norm(p["name"]): p for p in self.products}
        by_id = {p["id"]: p for p in self.products}
        for path, role in ((a, "product_additives"), (r, "reference")):
            if path is None or not path.is_file():
                self.detected[f"{role}_csv"] = None
                continue
            df = pd.read_csv(path, low_memory=False)
            ac = {k: _pick(list(df.columns), v) for k, v in ADD_COLS.items()}
            self.detected[f"{role}_csv"] = str(path)
            self.detected[f"{role}_columns"] = {k: v for k, v in ac.items() if v}
            if not ac["code"]:
                continue
            for _, row in df.iterrows():
                codes = _codes_from_cell(row[ac["code"]])
                if not codes:
                    continue
                code = codes[0]
                info = self.additive_info.setdefault(base_code(code), {"code": base_code(code), "name": None, "function": None,
                                                                       "notes": None, "source": None})
                for field in ("name", "function", "notes"):
                    col = ac[field]
                    if col and col != ac["code"] and pd.notna(row[col]) and str(row[col]).strip():
                        # The reference file wins over product-level rows; never overwrite reference text.
                        if info[field] is None or role == "reference":
                            info[field] = str(row[col]).strip()
                info["source"] = "additive reference CSV" if role == "reference" or info["source"] == "additive reference CSV" \
                    else "packaged additives CSV"
                if role == "product_additives" and ac["product"] and pd.notna(row[ac["product"]]):
                    key = str(row[ac["product"]])
                    prod = by_id.get(key) or by_name.get(norm(key))
                    if prod is not None and code not in prod["additive_codes"]:
                        prod["additive_codes"].append(code)

    # ------------------------------------------------------------ views
    def additive_details(self, codes: list[str]) -> list[dict]:
        out = []
        for c in codes:
            info = self.additive_info.get(base_code(c))
            out.append({"code": c, "ins_label": f"INS {c}", "name": info and info["name"], "function": info and info["function"],
                        "notes": info and info["notes"], "source": info["source"] if info else None,
                        "in_reference": info is not None})
        return out

    def nutrition_view(self, rec: dict, serving_grams: float | None = None) -> dict:
        serving = rec.get("serving_size_g")
        basis_known = serving is not None and abs(serving - 100) < 1e-6
        items, missing = [], []
        for key, label, unit, _ in NUTRIENT_COLS:
            if key not in rec["nutrients_raw"]:
                continue
            v = rec["nutrients_raw"][key]
            flags = []
            if v == 0 and key in ZERO_MEANS_MISSING:
                v, flags = None, ["stored as 0 in the dataset; treated as not recorded"]
            if v is not None and basis_known and v > PLAUSIBLE_MAX_100G.get(key, float("inf")):
                flags.append("implausible value in dataset; shown as reported")
            if v is None:
                missing.append(label)
            scaled = round(v * serving_grams / 100, 3) if (v is not None and basis_known and serving_grams) else None
            items.append({"key": key, "label": label, "unit": unit, "value": v, "per_serving": scaled, "flags": flags})
        return {
            "source": "SmartPlateAI packaged-food dataset (packaged_foods_india_clean.csv)",
            "basis": "per 100 g (dataset serving size recorded as 100 g)" if basis_known else
                     "basis not stated in the dataset (values as stored; may be per 100 g or per serving)",
            "basis_known": basis_known,
            "dataset_serving_size_g": serving,
            "serving_grams": serving_grams if basis_known else None,
            "nutrients": items,
            "not_available": missing,
        }

    def product_view(self, rec: dict, serving_grams: float | None = None) -> dict:
        return {"id": rec["id"], "name": rec["name"], "brand": rec["brand"], "category": rec["category"],
                "ingredients_text": rec["ingredients_text"], "allergens_text": rec["allergens_text"],
                "additive_codes": rec["additive_codes"], "price": rec.get("price"), "nutrition": self.nutrition_view(rec, serving_grams)}

    def get(self, product_id: str) -> dict | None:
        if not self.load():
            return None
        return next((p for p in self.products if p["id"] == product_id), None)

    # ------------------------------------------------------------ matching
    def _found(self, wanted: list[str], have: set[str]) -> list[str]:
        """Which of the record's tokens appear in the text (exact, OCR-folded, or close spelling)."""
        hits = []
        for t in wanted:
            ft = fold(t)
            if t in have or ft in have or any(similar(ft, h) for h in have):
                hits.append(t)
        return hits

    def score(self, rec: dict, have: set[str]) -> tuple[float, dict]:
        """IDF-weighted share of the record's brand and name words found in the text. Words shared by many products
        ('noodles', 'chips') count little; distinctive words (brand, flavour) count a lot."""
        nt, bt = rec["_name_toks"], rec["_brand_toks"]
        distinctive_name = [t for t in nt if t not in GENERIC_NAME_WORDS]
        name_hits, brand_hits = self._found(distinctive_name, have), self._found(bt, have)
        w = lambda t: self._idf.get(t, 1.0)  # noqa: E731
        name_w, brand_w = sum(w(t) for t in distinctive_name), sum(w(t) for t in bt)
        name_frac = sum(w(t) for t in name_hits) / name_w if name_w else 0.0
        brand_frac = sum(w(t) for t in brand_hits) / brand_w if brand_w else 0.0
        # The brand owner (e.g. the manufacturer) is often printed only in small type, so a very complete name match
        # may stand without it; the brand still raises the score when it is found.
        s = max(0.35 * brand_frac + 0.65 * name_frac, 0.85 * name_frac) if bt else name_frac * 0.85
        return round(s, 3), {"name_tokens_matched": len(name_hits), "name_tokens": len(distinctive_name), "brand_matched": bool(bt) and brand_frac >= 0.99,
                             "matched_words": name_hits + brand_hits, "missing_words": [t for t in distinctive_name if t not in name_hits]}

    def rank(self, text: str, limit: int = 5, identity_text: str | None = None) -> list[dict]:
        """identity_text: the text that names the product (front of pack / vision reading). Variant conflicts are
        checked only there, so an ingredient such as 'wheat flour (atta)' does not count as the 'Atta' variant."""
        if not self.load():
            return []
        have = {t for t in text_tokens(text) if t not in GENERIC}
        ident = {t for t in text_tokens(identity_text) if t not in GENERIC} if identity_text else have
        if identity_text and ident:
            have = ident
        if not have:
            return []
        scored = []
        for rec in self.products:
            s, ev = self.score(rec, have)
            if s > 0:
                scored.append((s, rec, ev))
        scored.sort(key=lambda x: -x[0])
        top = scored[:max(limit, 8)]
        # Variant check: words that distinguish one close candidate from another (e.g. 'masala' vs 'chicken'). If the
        # text contains another candidate's distinguishing word that this record lacks, the record is penalised.
        for i, (s, rec, ev) in enumerate(top):
            mine = set(rec["_name_toks"]) | set(rec["_brand_toks"])
            conflicts = []
            same_brand = rec.get("brand") and any(
                rec2.get("brand") and rec.get("brand", "").lower() == rec2.get("brand", "").lower()
                for _, rec2, _ in top if rec2 is not rec
            )
            for s2, rec2, _ in top:
                if rec2 is rec or s2 < 0.3:
                    continue
                for t in set(rec2["_name_toks"]) - mine:
                    if t in VARIANT_WORDS and same_brand:
                        continue
                    if self._idf.get(t, 0) >= 0.5 and self._found([t], ident) and t not in conflicts:
                        conflicts.append(t)
            ev["conflicting_words"] = conflicts
            if conflicts:
                top[i] = (round(s * 0.7, 3), rec, ev)
        top.sort(key=lambda x: -x[0])
        return [{"score": s, "product": rec, "evidence": ev} for s, rec, ev in top[:limit]]

    def by_barcode(self, code: str | None) -> dict | None:
        if not code or not self.load():
            return None
        return next((p for p in self.products if same_barcode(p.get("barcode"), code)), None)

    def match(self, text: str, barcode: str | None = None, net_quantity_g: float | None = None, identity_text: str | None = None) -> dict:
        """Priority: 1) exact barcode in the dataset; 2) brand + product name + variant words in the text;
        3) otherwise candidates for the user to choose from, or 'unmatched'. The returned confidence is the
        match score described above (share of weighted record words found), not a probability."""
        hit = self.by_barcode(barcode)
        if hit is not None:
            return {"status": "matched", "method": "barcode", "confidence": 1.0, "product_id": hit["id"],
                    "candidates": [{"id": hit["id"], "name": hit["name"], "brand": hit["brand"], "score": 1.0, "evidence": {"barcode": barcode}}],
                    "reason": f"The barcode {barcode} read from the pack matches this dataset record exactly."}
        ranked = self.rank(text, limit=5, identity_text=identity_text)
        if net_quantity_g:  # prefer the record whose pack size matches the label (tie-breaker only)
            for r in ranked:
                q = r["product"].get("quantity_g")
                if q:
                    r["evidence"]["size_matches"] = abs(q - net_quantity_g) <= max(1.0, 0.02 * q)
                    r["score"] = round(r["score"] + (0.03 if r["evidence"]["size_matches"] else -0.03), 3)
            ranked.sort(key=lambda r: -r["score"])
        def anchored(r: dict) -> bool:
            """Require brand, product-line, or genuinely rare product-name evidence."""
            ev, nt = r["evidence"], r["product"]["_name_toks"]
            if ev["brand_matched"]:
                return True
            if nt and nt[0] in ev["matched_words"] and nt[0] not in IDENTITY_WEAK:
                return True
            rare_df = max(3, int(0.01 * len(self.products)))
            return any(t not in IDENTITY_WEAK and self._df.get(t, 0) <= rare_df for t in ev["matched_words"] if t in nt)
        for r in ranked:
            r["evidence"]["anchored"] = anchored(r)
        candidates = [{"id": r["product"]["id"], "name": r["product"]["name"], "brand": r["product"]["brand"],
                       "score": r["score"], "evidence": r["evidence"]} for r in ranked if r["score"] >= 0.2 and r["evidence"]["anchored"]]
        if not ranked:
            return {"status": "unmatched", "method": None, "confidence": 0.0, "product_id": None, "candidates": [],
                    "reason": "No product name or brand from the dataset was found in the label text."}
        top = ranked[0]
        second = ranked[1]["score"] if len(ranked) > 1 else 0.0
        ev = top["evidence"]
        has_brand = bool(top["product"]["_brand_toks"])
        product_is_strong = (top["score"] >= 0.7 and top["score"] - second >= 0.08 and not ev["conflicting_words"] and ev["anchored"]
                             and (ev["brand_matched"] or not has_brand or
                                  (ev["name_tokens"] and ev["name_tokens_matched"] / ev["name_tokens"] >= 0.85))
                             and (ev["name_tokens_matched"] >= 2 or (ev["name_tokens_matched"] >= 1 and ev["brand_matched"])))
        if product_is_strong:
            return {"status": "matched", "method": "text", "confidence": top["score"], "product_id": top["product"]["id"],
                    "candidates": candidates,
                    "reason": "Words of this record found on the pack: " + ", ".join(ev["matched_words"]) + "."
                              + ("" if ev["brand_matched"] or not has_brand else
                                 f" The brand owner '{top['product']['brand']}' was not seen on the pack, but the product name matched almost completely.")}
        if candidates:
            why = ("words of another variant were also found (" + ", ".join(ev["conflicting_words"]) + ")") if ev["conflicting_words"] else \
                  "two products match almost equally well" if top["score"] - second < 0.08 else \
                  "too few distinctive words matched" if top["score"] < 0.7 else "the brand was not found"
            return {"status": "uncertain", "method": None, "confidence": top["score"], "product_id": None, "candidates": candidates,
                    "reason": f"Some words match dataset products, but not strongly enough to pick one automatically: {why}."}
        return {"status": "unmatched", "method": None, "confidence": top["score"], "product_id": None, "candidates": [],
                "reason": "The label text does not match any dataset product closely enough."}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        if not self.load():
            return []
        q = norm(query)
        out = []
        for rec in self.products:
            hay = norm(f"{rec['brand'] or ''} {rec['name']}")
            if q and q in hay:
                s = 1.0
            else:
                qt = [t for t in tokens(query)]
                ht = set(tokens(hay))
                s = (len(self._found(qt, ht)) / len(qt)) if qt else 0.0
            if s >= 0.5:
                out.append((s, rec))
        out.sort(key=lambda x: (-x[0], x[1]["name"]))
        return [{"id": r["id"], "name": r["name"], "brand": r["brand"], "score": round(s, 3)} for s, r in out[:limit]]
