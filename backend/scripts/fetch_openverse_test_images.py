"""Download openly licensed real photos (CC0, Public Domain Mark, CC BY) from Openverse for recognition tests.

Each image is saved with its provenance in ATTRIBUTION.csv next to it (title, creator, license, source page), which is
what CC BY requires. Images are test data only: they are never used for training or calibration.

    python scripts/fetch_openverse_test_images.py --set non_food        -> data_nonfood/general
    python scripts/fetch_openverse_test_images.py --set food_in_context -> data_eval/food_in_context
    python scripts/fetch_openverse_test_images.py --set unsupported_food -> data_eval/unsupported_food

Search results are not ground truth: review every downloaded image and delete wrong ones (then their CSV rows are dropped
by --prune). The tests only use files listed in ATTRIBUTION.csv.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

BACKEND = Path(__file__).resolve().parents[1]
API = "https://api.openverse.org/v1/images/"
LICENSES = "cc0,pdm,by"
UA = {"User-Agent": "SmartPlateAI-test-data/1.0 (recognition test set; attribution kept)"}
FIELDS = ["file", "category", "query", "title", "creator", "license", "license_version", "license_url", "source_page", "image_url"]

SETS = {
    "non_food": (BACKEND / "data_nonfood" / "general", {
        "person": ["portrait man face", "portrait woman", "people standing street"],
        "mobile_phone": ["smartphone", "mobile phone on desk"],
        "laptop": ["laptop computer", "laptop on desk"],
        "keyboard": ["computer keyboard"],
        "shoe": ["sneakers shoes", "leather shoes"],
        "vehicle": ["car parked street", "bicycle", "bus"],
        "furniture": ["sofa living room", "wooden chair"],
        "scenery": ["mountain landscape", "beach sea", "forest trail"],
        "other_object": ["backpack", "umbrella", "books on shelf", "wrist watch"],
    }),
    "food_in_context": (BACKEND / "data_eval" / "food_in_context", {
        "Pizza": ["person eating pizza"], "Burger": ["man eating burger"], "Banana": ["woman holding banana"],
        "Apple": ["child eating apple"], "Donut": ["holding donut"], "Hot Dog": ["eating hot dog"],
        "Strawberry": ["holding strawberries hand"], "Fries": ["eating french fries"], "Orange": ["holding orange fruit"],
        "Sandwich": ["eating sandwich"], "Taco": ["eating taco"],
    }),
    # Packaged things that are NOT food: being packaged must never make an image "food".
    "non_food_packaged": (BACKEND / "data_nonfood" / "packaged_objects", {
        "medicine": ["medicine box pills", "pill bottle", "blister pack tablets"],
        "cosmetics": ["cosmetics bottles", "lipstick", "perfume bottle"],
        "toiletries": ["shampoo bottle", "toothpaste tube", "soap bar packaging"],
        "household": ["detergent bottle", "cardboard box package"],
        "electronics_box": ["smartphone box packaging", "headphones box"],
    }),
    # Unwrapped or served food photographed together with its packaging: the food must not be rejected.
    "food_with_packaging": (BACKEND / "data_eval" / "food_with_packaging", {
        "Pizza": ["pizza in box"], "Fries": ["french fries paper bag"], "Burger": ["burger wrapper fries"],
        "Donut": ["donuts box"], "Sandwich": ["sandwich wrapped paper"], "Banana": ["bananas plastic bag"],
        "Strawberry": ["strawberries punnet"], "Apple": ["apples bag supermarket"],
    }),
    "unsupported_food": (BACKEND / "data_eval" / "unsupported_food", {
        "sushi": ["sushi plate"], "ramen": ["ramen bowl"], "salad": ["green salad bowl"], "pancakes": ["pancakes stack"],
        "curry": ["curry rice"], "cake": ["chocolate cake slice"], "spaghetti": ["spaghetti plate"], "dumplings": ["dumplings"],
    }),
}


def search(query: str, n: int) -> list[dict]:
    """Openverse search; retried, and an empty list (query skipped) if the service keeps failing."""
    q = urllib.parse.urlencode({"q": query, "license": LICENSES, "page_size": max(n * 3, 10), "mature": "false"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{API}?{q}", headers=UA), timeout=60) as r:
                return json.load(r)["results"]
        except Exception as exc:  # noqa: BLE001
            print(f"   search failed ({type(exc).__name__}), attempt {attempt + 1}/3")
            time.sleep(10)
    return []


def write_csv(csv_path: Path, rows: list[dict], out: Path) -> list[dict]:
    rows = [r for r in rows if (out / r["file"]).is_file()]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows


def fetch_image(url: str) -> Image.Image | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            img = Image.open(io.BytesIO(r.read(15_000_000)))
            img.load()
        return img.convert("RGB") if min(img.size) >= 200 else None
    except Exception:  # noqa: BLE001 - dead links and odd formats are skipped
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=sorted(SETS), required=True)
    ap.add_argument("--per-query", type=int, default=3)
    ap.add_argument("--prune", action="store_true", help="only drop CSV rows whose file was deleted after review")
    args = ap.parse_args()
    out, queries = SETS[args.set]
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "ATTRIBUTION.csv"
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8"))) if csv_path.is_file() else []
    if not args.prune:
        seen = {r["image_url"] for r in rows}
        for category, qs in queries.items():
            for query in qs:
                got = 0
                for item in search(query, args.per_query):
                    if got >= args.per_query or item["url"] in seen:
                        continue
                    img = fetch_image(item["url"])
                    if img is None:
                        continue
                    img.thumbnail((1280, 1280))
                    name = f"{category.lower().replace(' ', '_')}_{item['id'][:8]}.jpg"
                    img.save(out / name, "JPEG", quality=92)
                    rows.append({"file": name, "category": category, "query": query, "title": item.get("title") or "",
                                 "creator": item.get("creator") or "", "license": item["license"],
                                 "license_version": item.get("license_version") or "", "license_url": item.get("license_url") or "",
                                 "source_page": item.get("foreign_landing_url") or "", "image_url": item["url"]})
                    seen.add(item["url"])
                    got += 1
                print(f"{category:14} {query!r}: {got}")
                write_csv(csv_path, rows, out)  # saved after every query
                time.sleep(3.5)  # stay well inside Openverse's anonymous rate limit
    rows = write_csv(csv_path, rows, out)
    print(f"{len(rows)} images listed in {csv_path}")


if __name__ == "__main__":
    main()
