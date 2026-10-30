"""Train the freshness head on top of the PRODUCTION food model's embeddings (no CNN retraining).

Uses only manifest rows with a trusted freshness label (freshness_trainable == True, label Fresh/Rotten).
  train split -> fit logistic regression
  val split   -> choose the two thresholds (fresh / possibly spoiled) and report metrics
  test split  -> never used here
Writes models/production/freshness/{freshness_head.npz, freshness_config.json} and reports/freshness/report.md.

Run from D:\\SmartPlateAI\\backend:
  .\\.venv\\Scripts\\python.exe scripts\\train_freshness_head.py --per-class-cap 1500
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.ml.freshness import choose_thresholds, fit_logistic, predict_proba  # noqa: E402
from app.ml.recognizer import FoodRecognizer, decode_upload, sha256_file  # noqa: E402

MANIFEST = BACKEND_DIR / "data_prep" / "split_manifest.csv"
OUT = BACKEND_DIR / "models" / "production" / "freshness"


def label_of(v) -> int | None:
    s = str(v).strip().lower()
    if s.startswith("fresh"):
        return 0
    if s.startswith(("rot", "spoil", "stale")):
        return 1
    return None


def truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def features(rec: FoodRecognizer, paths: list[str], batch: int = 32) -> tuple[np.ndarray, list[int]]:
    feats, kept = [], []
    for i in range(0, len(paths), batch):
        xs, idx = [], []
        for j, p in enumerate(paths[i:i + batch]):
            try:
                xs.append(rec.prepare(decode_upload(Path(p).read_bytes())))
                idx.append(i + j)
            except Exception:  # noqa: BLE001
                continue
        if xs:
            _, f, _ = rec.embed(np.stack(xs))
            feats.append(f)
            kept += idx
        print(f"  {min(i + batch, len(paths))}/{len(paths)}", end="\r")
    print()
    return (np.concatenate(feats) if feats else np.zeros((0, 1280))), kept


def main() -> None:
    import pandas as pd  # noqa: PLC0415
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class-cap", type=int, default=1500, help="max train images per (food, label)")
    ap.add_argument("--min-per-label", type=int, default=30, help="a food needs this many train images of BOTH labels")
    ap.add_argument("--target-precision", type=float, default=0.9)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rec = FoodRecognizer(allow_uncalibrated=True)
    if not rec.load():
        sys.exit(f"Food model not ready: {rec.status_message}")
    df = pd.read_csv(MANIFEST, low_memory=False)
    if "freshness_label" not in df.columns:
        sys.exit("The manifest has no freshness_label column.")
    df["y"] = df["freshness_label"].map(label_of)
    if "freshness_trainable" in df.columns:
        df = df[df["freshness_trainable"].map(truthy)]
    df = df[df["y"].notna() & df["new_split"].isin(["train", "val"])]
    counts = df[df.new_split == "train"].groupby(["food", "y"]).size().unstack(fill_value=0)
    foods = [f for f in counts.index if counts.loc[f].min() >= args.min_per_label] if len(counts.columns) == 2 else []
    if not foods:
        sys.exit("No food has enough trusted Fresh AND Rotten training images.")
    df = df[df.food.isin(foods)]
    # Shuffle, then keep up to the cap per (food, label). (groupby().apply() drops the grouping columns in pandas >= 3,
    # which removed the 'y' label column and crashed the script after feature extraction.)
    tr = df[df.new_split == "train"].sample(frac=1, random_state=args.seed).groupby(["food", "y"]).head(args.per_class_cap)
    va = df[df.new_split == "val"]
    print(f"Foods: {foods}\nTrain {len(tr)} / val {len(va)} images")
    x_tr, k_tr = features(rec, tr.image_path.tolist())
    x_va, k_va = features(rec, va.image_path.tolist())
    y_tr, y_va = tr.y.to_numpy()[k_tr].astype(int), va.y.to_numpy()[k_va].astype(int)
    head = fit_logistic(x_tr, y_tr)
    p_va = predict_proba(head, x_va)
    th = choose_thresholds(p_va, y_va, args.target_precision)
    acc05 = float(((p_va >= 0.5) == y_va.astype(bool)).mean())
    per_food = {}
    for f in foods:
        m = va.food.to_numpy()[k_va] == f
        if m.any():
            per_food[f] = {"n": int(m.sum()), "accuracy_at_0.5": float(((p_va[m] >= 0.5) == y_va[m].astype(bool)).mean())}
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / "freshness_head.npz", **head)
    cfg = {"food_model_sha256": sha256_file(rec.model_dir / "best.keras"), "supported_foods": foods,
           "t_fresh": th["t_fresh"], "t_spoiled": th["t_spoiled"], "validation": {**th, "accuracy_at_0.5": acc05, "per_food": per_food},
           "trained_on": {"train_images": int(len(y_tr)), "val_images": int(len(y_va))}, "created": datetime.now().isoformat(timespec="seconds"),
           "note": "Thresholds chosen on the validation split; the test split was not used."}
    (OUT / "freshness_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    rep = BACKEND_DIR / "reports" / "freshness"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "report.md").write_text("# Freshness head\n\n```json\n" + json.dumps(cfg, indent=2) + "\n```\n", encoding="utf-8")
    print(json.dumps(cfg["validation"], indent=2))
    print(f"Wrote {OUT}. Restart the API to load it.")


if __name__ == "__main__":
    main()
