"""Download a small, real packaged-food evaluation set from Open Food Facts (OFF).

For each product: the front, ingredients and nutrition-table photos (full resolution) plus OFF's contributor-entered data
(barcode, name, brand, per-100 g nutriments, ingredients text) as a reference to compare the label reader against.
OFF images are CC BY-SA 3.0 (contributors of Open Food Facts) and the data is ODbL; the source page of each product is
recorded in data_eval/packaged/MANIFEST.json. OFF data is crowd-sourced: it is a reference, not laboratory truth.

    python scripts/fetch_off_packaged_test_set.py --country india --n 10
    python scripts/fetch_off_packaged_test_set.py --country united-kingdom --n 5
"""
from __future__ import annotations

import argparse
import io
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "data_eval" / "packaged"
UA = {"User-Agent": "SmartPlateAI-test-data/1.0 (packaged label evaluation; attribution kept)"}
FIELDS = ("code,product_name,brands,quantity,image_front_url,image_ingredients_url,image_nutrition_url,nutriments,"
          "ingredients_text,nutrition_data_per,countries_tags")
KEYS = {"energy-kcal_100g": "energy_kcal", "proteins_100g": "protein_g", "carbohydrates_100g": "carbohydrate_g", "sugars_100g": "total_sugars_g",
        "fat_100g": "total_fat_g", "saturated-fat_100g": "saturated_fat_g", "fiber_100g": "dietary_fibre_g", "sodium_100g": "sodium_g"}


def get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.load(r)


def full_res(url: str) -> str:
    return url.rsplit(".", 2)[0] + ".full.jpg" if url.count(".") >= 2 else url  # front_en.12.400.jpg -> front_en.12.full.jpg


def fetch_image(url: str) -> Image.Image | None:
    for u in (full_res(url), url):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as r:
                img = Image.open(io.BytesIO(r.read(20_000_000)))
                img.load()
            return img.convert("RGB")
        except Exception:  # noqa: BLE001
            continue
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default="india")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--prefix", default="", help="only barcodes starting with this (890 = registered in India)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    man_path = OUT / "MANIFEST.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8")) if man_path.is_file() else []
    have = {m["barcode"] for m in manifest}
    # The search-a-licious service lists candidates (the classic /api/v2/search is often overloaded); details come per product.
    query = (f'countries_tags:"en:{args.country}" AND states_tags:"en:nutrition-facts-completed" '
             'AND states_tags:"en:ingredients-completed"')
    q = urllib.parse.urlencode({"q": query, "page_size": 100, "fields": "code", "sort_by": "-unique_scans_n"})
    codes = [h["code"] for h in get_json(f"https://search.openfoodfacts.org/search?{q}").get("hits", []) if h.get("code")]
    codes = [c for c in codes if c.startswith(args.prefix)] if args.prefix else codes
    added = 0
    for code in codes:
        if added >= args.n:
            break
        if code in have:
            continue
        try:
            p = get_json(f"https://world.openfoodfacts.org/api/v2/product/{code}?fields={FIELDS}").get("product") or {}
        except Exception:  # noqa: BLE001
            continue
        time.sleep(0.7)
        code, n = p.get("code") or code, p.get("nutriments") or {}
        if not code or code in have or not all(p.get(k) for k in ("image_front_url", "image_ingredients_url", "image_nutrition_url")):
            continue
        if n.get("energy-kcal_100g") is None or not p.get("product_name"):
            continue
        imgs = {side: fetch_image(p[f"image_{side}_url"]) for side in ("front", "ingredients", "nutrition")}
        if any(v is None for v in imgs.values()):
            continue
        d = OUT / code
        d.mkdir(exist_ok=True)
        for side, img in imgs.items():
            img.thumbnail((2400, 2400))
            img.save(d / f"{side}.jpg", "JPEG", quality=92)
        manifest.append({"barcode": code, "country": args.country, "product_name": p.get("product_name"), "brands": p.get("brands"),
                         "quantity": p.get("quantity"), "ingredients_text": p.get("ingredients_text"),
                         "nutrition_data_per": p.get("nutrition_data_per"),
                         "reference_per_100g": {v: n.get(k) for k, v in KEYS.items() if n.get(k) is not None},
                         "source_page": f"https://world.openfoodfacts.org/product/{code}",
                         "image_urls": {s: full_res(p[f"image_{s}_url"]) for s in imgs},
                         "license": "Images: CC BY-SA 3.0, contributors of Open Food Facts; data: ODbL"})
        have.add(code)
        added += 1
        man_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")  # saved after every product
        print(f"{code} {p.get('brands')} | {p.get('product_name')}".encode("ascii", "replace").decode())
        time.sleep(1.0)
    man_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{added} added, {len(manifest)} products in {man_path}")


if __name__ == "__main__":
    main()
