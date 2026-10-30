"""Reference nutrition lookup from the project's food CSV. Missing nutrients stay None (never 0)."""
from __future__ import annotations

import json
import math
import os
import re
import threading
from pathlib import Path

import pandas as pd

from app.data.class_references import GENERIC_CAVEATS, is_category, record_for

BACKEND_DIR = Path(__file__).resolve().parents[2]
UNITS = {"kcal": "kcal", "mg": "mg", "ug": "µg", "g": "g"}
SUFFIX = re.compile(r"_(kcal|mg|ug|g)$")
BASIS = "per 100 g (USDA FoodData Central reference record)"
NOTE = ("Reference values for this type of food, not measurements of the photographed item. Real nutrition depends on portion size, "
        "ripeness and preparation.")


class NutritionReference:
    def __init__(self, csv_path: str | Path | None = None) -> None:
        self.csv_path = Path(csv_path) if csv_path else None
        self._records: dict[str, dict] | None = None
        self._lock = threading.Lock()
        self.error: str | None = None
        self.conflicts: dict[str, int] = {}

    def _resolve(self) -> Path | None:
        if self.csv_path:
            return self.csv_path
        if os.environ.get("FOOD_NUTRITION_CSV"):
            return Path(os.environ["FOOD_NUTRITION_CSV"])
        paths = BACKEND_DIR / "reports" / "dataset_paths.json"
        if paths.is_file():
            p = json.loads(paths.read_text(encoding="utf-8")).get("food_csv")
            return Path(p) if p else None
        return None

    def load(self) -> bool:
        """One reference record per food, chosen deterministically.

        The food CSV has one row per training image (tens of thousands of rows), so a food appears many times. The old
        code kept whichever row came first in the file, so the profile depended on row order (for example a row from a
        'rotten' image group linked to a different FDC record). Rule now: group rows by food name (case-insensitive),
        take the FDC record used by most rows (ties: the lowest FDC id), and use that record's values. The image's
        freshness/condition plays no part. Foods whose rows point to different records are counted in `conflicts`."""
        with self._lock:
            if self._records is not None:
                return True
            path = self._resolve()
            if path is None or not path.is_file():
                self.error = "Nutrition reference data was not found."
                return False
            header = pd.read_csv(path, nrows=0).columns
            nutrients = [c for c in header if SUFFIX.search(c)]
            df = pd.read_csv(path, usecols=["food", "fdc_id", *nutrients])
            df = df[df["food"].notna()].copy()
            df["_key"] = df["food"].astype(str).str.strip().str.casefold()
            records: dict[str, dict] = {}
            conflicts: dict[str, int] = {}
            for key, g in df.groupby("_key", sort=True):
                ids = g["fdc_id"].dropna()
                if len(ids):
                    counts = ids.astype("int64").value_counts()
                    best = int(sorted(counts[counts == counts.max()].index)[0])
                    rows = g[g["fdc_id"] == best]
                else:
                    best, rows = None, g
                profiles = g[nutrients].round(4).drop_duplicates()
                if len(profiles) > 1:
                    conflicts[str(g["food"].iloc[0])] = int(len(profiles))
                row = rows.iloc[0]
                records[key] = {"food": str(g["food"].iloc[0]).strip(), "fdc_id": best,
                                "values": {c: (None if pd.isna(row[c]) else float(row[c])) for c in nutrients},
                                "rows": int(len(g)), "rows_with_this_record": int(len(rows)), "profiles": int(len(profiles))}
            self._records, self.conflicts = records, conflicts
            return True

    def lookup(self, food: str, serving_grams: float | None = None) -> dict | None:
        """Deterministic: the same food name and serving size always give the same values (freshness is not an input)."""
        key = str(food).strip().casefold()
        if not self.load() or key not in (self._records or {}):
            return None
        rec = self._records[key]
        items, missing = [], []
        for key, val in rec["values"].items():
            unit = UNITS[SUFFIX.search(key).group(1)]
            label = SUFFIX.sub("", key).replace("_", " ").capitalize()
            per_serving = None if (val is None or serving_grams is None) else round(val * serving_grams / 100.0, 3)
            if val is None:
                missing.append(label)
            items.append({"key": key, "label": label, "unit": unit, "per_100g": val, "per_serving": per_serving})
        usda = record_for(rec["food"], rec["fdc_id"])  # which food the numbers belong to (the dataset stores only the id)
        generic = is_category(rec["food"])
        basis = (f"per 100 g (USDA FoodData Central {usda['data_type']} record {usda['fdc_id']}: {usda['description']})" if usda else BASIS)
        return {"basis": basis, "source_fdc_id": rec["fdc_id"], "is_estimate": True,
                "note": NOTE + (f" Generic reference for the category '{rec['food']}': the specific type was not determined. "
                                f"{GENERIC_CAVEATS.get(rec['food'], '')}" if generic else ""),
                "serving_grams": serving_grams,
                "matched_description": usda["description"] if usda else None, "data_type": usda["data_type"] if usda else None,
                "source_url": usda["url"] if usda else None, "generic_category_reference": generic,
                "reference": {"food": rec["food"], "fdc_id": rec["fdc_id"], "selection": "FDC record used by most rows for this food",
                              "description": usda["description"] if usda else None,
                              "rows_for_food": rec["rows"], "rows_with_this_record": rec["rows_with_this_record"],
                              "distinct_profiles_in_dataset": rec["profiles"]},
                "serving_note": ("Scaled linearly from the per-100 g values using the serving size you entered." if serving_grams else
                                 "No serving size was given, so only per-100 g values are shown."),
                "nutrients": items, "not_available": missing}