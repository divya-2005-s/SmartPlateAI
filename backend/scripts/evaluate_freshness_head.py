"""Evaluate the installed freshness head ONCE on the held-out TEST split (after train_freshness_head.py chose everything
on train/validation). Records the result in freshness_config.json ("test_metrics") and reports/freshness/test_eval_*.json.

Uses the same trusted labels as training (freshness_trainable == True, Fresh/Rotten) and the same group-aware split
(near-duplicate families never cross splits). Images are dataset photos, so the numbers describe this dataset, not
real-world phone photos.

Run from D:\\SmartPlateAI\\backend:
  .\\.venv\\Scripts\\python.exe scripts\\evaluate_freshness_head.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from app.ml.freshness import decide, predict_proba  # noqa: E402
from app.ml.recognizer import FoodRecognizer, sha256_file  # noqa: E402
from train_freshness_head import MANIFEST, OUT, features, label_of, truthy  # noqa: E402


def summarise(y: np.ndarray, decisions: np.ndarray) -> dict:
    """y: 1 = rotten. decisions: fresh / possibly_spoiled / uncertain."""
    decided = decisions != "uncertain"
    pred_rotten = decisions == "possibly_spoiled"
    out = {"n": int(len(y)), "coverage": round(float(decided.mean()), 4) if len(y) else None,
           "confusion": {t: {d: int(((y == (1 if t == "rotten" else 0)) & (decisions == d)).sum())
                             for d in ("fresh", "uncertain", "possibly_spoiled")} for t in ("fresh", "rotten")}}
    if decided.any():
        yd, pd_ = y[decided], pred_rotten[decided]
        out["accuracy_on_decided"] = round(float((yd == pd_).mean()), 4)
        for name, want in (("possibly_spoiled", True), ("fresh", False)):
            called = pd_ == want
            out[f"precision_{name}"] = round(float((yd[called] == want).mean()), 4) if called.any() else None
            truth = yd == want
            out[f"recall_{name}"] = round(float((pd_[truth] == want).mean()), 4) if truth.any() else None
    return out


def main() -> None:
    import pandas as pd  # noqa: PLC0415
    cfg_path = OUT / "freshness_config.json"
    if not cfg_path.is_file():
        sys.exit("No freshness head installed; run scripts/train_freshness_head.py first.")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    d = np.load(OUT / "freshness_head.npz")
    head = {k: d[k] for k in ("mean", "scale", "w", "b")}
    rec = FoodRecognizer(allow_uncalibrated=True)
    if not rec.load():
        sys.exit(f"Food model not ready: {rec.status_message}")
    if sha256_file(rec.model_dir / "best.keras") != cfg.get("food_model_sha256"):
        sys.exit("The freshness head was trained on a different food model; not evaluating.")

    df = pd.read_csv(MANIFEST, low_memory=False)
    df["y"] = df["freshness_label"].map(label_of)
    df = df[df["freshness_trainable"].map(truthy) & df["y"].notna() & (df["new_split"] == "test")
            & df["food"].isin(cfg["supported_foods"])]
    print(f"Test images: {len(df)}")
    x, kept = features(rec, df.image_path.tolist())
    y = df.y.to_numpy()[kept].astype(int)
    foods = df.food.to_numpy()[kept]
    p = predict_proba(head, x)
    decisions = np.array([decide(float(v), cfg["t_fresh"], cfg["t_spoiled"]) for v in p], dtype=object)
    metrics = {"overall": summarise(y, decisions),
               "per_food": {f: summarise(y[foods == f], decisions[foods == f]) for f in sorted(set(foods))},
               "evaluated": datetime.now().isoformat(timespec="seconds"),
               "note": "Held-out test split of the project's dataset photos, evaluated once; not real-world phone photos."}
    cfg["test_metrics"] = metrics
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    rep = BACKEND_DIR / "reports" / "freshness" / f"test_eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics["overall"], indent=2))
    print("Report:", rep)


if __name__ == "__main__":
    main()
