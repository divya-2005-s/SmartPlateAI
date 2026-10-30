"""Copy the reference CSVs the server needs into deploy/reference_data (the Docker build copies that folder).

The datasets live outside the project (see backend/reports/dataset_paths.json); the image must carry its own copies.
Writes deploy/reference_data/MANIFEST.json with each file's size and SHA-256 so the deployed data can be verified.
No database, .env file, model or user data is copied; the food CSV is reduced to the columns the server uses.

    python scripts/prepare_deploy_data.py
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND.parent / "deploy" / "reference_data"
WANTED = {"food_csv": "final_food_nutrient_dataset.csv", "packaged_csv": "packaged_foods_india_clean.csv",
          "additives_csv": "packaged_food_additives.csv", "additive_ref_csv": "additive_reference_populated.csv"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def slim_food_csv(src: Path, dst: Path) -> None:
    """Keep food, fdc_id and the nutrient columns of every row (row counts decide each food's record, so no row is dropped);
    drop image names, local file paths, splits and source details, which the server never needs."""
    import pandas as pd
    header = pd.read_csv(src, nrows=0).columns
    keep = ["food", "fdc_id", *[c for c in header if re.search(r"_(kcal|mg|ug|g)$", c)]]
    pd.read_csv(src, usecols=keep)[keep].to_csv(dst, index=False)


def main() -> None:
    paths = json.loads((BACKEND / "reports" / "dataset_paths.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for key, name in WANTED.items():
        src = Path(paths[key])
        if src.name != name:
            raise SystemExit(f"{key} points to {src.name}, expected {name}; update WANTED or the Dockerfile ENV paths")
        if not src.is_file():
            raise SystemExit(f"missing {src}")
        dst = OUT / name
        if key == "food_csv":
            slim_food_csv(src, dst)  # the training manifest: keep only what nutrition lookup needs (no image paths)
        else:
            shutil.copy2(src, dst)
        manifest[name] = {"bytes": dst.stat().st_size, "sha256": sha256(dst), "source_file": src.name}
        print(f"{name:40} {dst.stat().st_size:>12,} bytes")
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
