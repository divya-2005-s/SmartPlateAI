"""Evaluate the existing fresh/rotten condition classifier and (optionally) connect it to the app.

    cd D:\\SmartPlateAI\\backend
    .\\.venv\\Scripts\\python.exe scripts\\evaluate_condition_model.py ^
        --model "D:\\path\\to\\condition_classifier.keras" --classes "D:\\path\\to\\condition_classes.json" ^
        --csv "D:\\Food_Composition_Project\\output\\final_food_nutrient_dataset.csv" --image-root "D:\\Food_Composition_Project"
    (add --install to write models\\production\\condition\\condition_config.json after you have read the report)

What it does, in order (the test split is used only in step 6):
 1. Reads the dataset CSV and detects the image-path, condition-label and split columns (prints them).
 2. Optional (--leakage): average-hash every image and counts near-identical images shared between splits.
 3. Chooses the pixel preprocessing the model expects (raw 0-255, 0-1 or -1..1) by macro-F1 on VALIDATION images.
 4. Checks the class order on VALIDATION: if swapping fresh/rotten scores much better, it stops (reversed mapping).
 5. Calibrates fresh / rotten thresholds on VALIDATION for 90% precision; below them the result is "uncertain".
 6. Evaluates once on the TEST split: confusion matrix, precision, recall, F1, coverage.
 7. Writes reports\\condition_eval_<time>.json, and with --install the config the app needs. The model file itself
    is never modified or copied; the config stores its path and SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.ml.condition import class_role, preprocess_array  # noqa: E402
from app.ml.condition_eval import (ahash, choose_thresholds, cross_split_duplicates, decide_all, detect_columns,  # noqa: E402
                                   mapping_check, metrics, read_class_names, role_probs, split_role)

MODES = ("raw_0_255", "scale_0_1", "minus1_1")


def label_role(v) -> str:
    r = class_role(str(v))
    return r if r in ("fresh", "rotten") else "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--classes", required=True, help="class metadata JSON saved with the model")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--image-root", default="", help="folder that relative image paths are relative to")
    ap.add_argument("--per-class", type=int, default=400, help="max validation images per label used for steps 3-5")
    ap.add_argument("--test-max", type=int, default=4000)
    ap.add_argument("--leakage", action="store_true")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--target-precision", type=float, default=0.9)
    a = ap.parse_args()

    import tensorflow as tf  # noqa: PLC0415
    model_path = Path(a.model)
    classes = read_class_names(a.classes)
    print("Classes from metadata (model output order):", classes, "->", [class_role(c) for c in classes])
    if not any(class_role(c) == "fresh" for c in classes) or not any(class_role(c) == "rotten" for c in classes):
        sys.exit("The class list does not contain recognisable 'fresh' and 'rotten' classes; check --classes.")
    model = tf.keras.models.load_model(model_path, compile=False)
    size = int(model.input_shape[1] or 224)
    print("Model input:", model.input_shape, "-> using", size, "px")

    df = pd.read_csv(a.csv, low_memory=False)
    cols = detect_columns(list(df.columns))
    print("Detected columns:", cols)
    if not cols["path"] or not cols["condition"] or not cols["split"]:
        sys.exit("Need image-path, condition and split columns. Available: " + ", ".join(df.columns))
    df = df[[c for c in cols.values() if c]].dropna(subset=[cols["path"], cols["condition"]]).copy()
    df["role"] = df[cols["condition"]].map(label_role)
    df["split_role"] = df[cols["split"]].map(split_role)
    root = Path(a.image_root) if a.image_root else None
    df["abs"] = [str(Path(p) if Path(p).is_absolute() or root is None else root / p) for p in df[cols["path"]]]
    print("Rows by split and label:\n", df.groupby(["split_role", "role"]).size().to_string())
    if not (df["split_role"] == "validation").any() or not (df["split_role"] == "test").any():
        sys.exit("Both a validation and a test split are required (thresholds must not be tuned on test).")

    report: dict = {"model": str(model_path), "classes": classes, "columns": cols, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    if a.leakage:
        hashes: dict[str, list[int]] = {}
        for sr, g in df.groupby("split_role"):
            hs = []
            for p in g["abs"]:
                try:
                    hs.append(ahash(Image.open(p)))
                except OSError:
                    pass
            hashes[sr] = hs
        report["near_duplicates_across_splits"] = cross_split_duplicates(hashes)
        print("Identical images across splits (average hash):", report["near_duplicates_across_splits"])

    def predict(paths: list[str], mode: str) -> tuple[np.ndarray, list[int]]:
        out, kept = [], []
        for i in range(0, len(paths), 32):
            batch, idx = [], []
            for j, p in enumerate(paths[i:i + 32]):
                try:
                    batch.append(preprocess_array(Image.open(p), size, mode))
                    idx.append(i + j)
                except OSError:
                    continue
            if batch:
                y = np.asarray(model(np.stack(batch), training=False))
                if y.ndim == 1 or y.shape[1] == 1:
                    y = np.concatenate([1 - y.reshape(-1, 1), y.reshape(-1, 1)], axis=1)
                out.append(y)
                kept += idx
        return (np.concatenate(out) if out else np.zeros((0, len(classes)))), kept

    val = df[(df["split_role"] == "validation") & df["role"].isin(["fresh", "rotten"])]
    val = pd.concat([g.sample(min(len(g), a.per_class), random_state=0) for _, g in val.groupby("role")])
    vy_all = val["role"].to_numpy()
    best = None
    for mode in MODES:
        probs, kept = predict(list(val["abs"]), mode)
        if not len(kept):
            sys.exit("No validation images could be opened; check --image-root.")
        vy = vy_all[kept]
        pred = np.array([class_role(classes[i]) for i in probs.argmax(axis=1)], dtype=object)
        f1 = metrics(vy, pred)["macro_f1"]
        print(f"preprocessing {mode}: validation macro-F1 {f1}")
        if best is None or f1 > best[0]:
            best = (f1, mode, probs, vy)
    _, mode, vprobs, vy = best
    chk = mapping_check(vprobs, classes, vy)
    report.update({"preprocessing": mode, "mapping_check": chk})
    print("Class-order check on validation:", chk)
    if chk["likely_reversed"]:
        Path(BACKEND_DIR / "reports").mkdir(exist_ok=True)
        (BACKEND_DIR / "reports" / "condition_eval_REVERSED.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        sys.exit("STOP: the fresh/rotten class order looks reversed. Fix the class metadata JSON; nothing was installed.")
    pf, pr = role_probs(vprobs, classes)
    th = choose_thresholds(pf, pr, vy, target_precision=a.target_precision)
    report["thresholds"] = th
    print("Thresholds (validation):", th)

    test = df[(df["split_role"] == "test") & df["role"].isin(["fresh", "rotten"])]
    if len(test) > a.test_max:
        test = test.sample(a.test_max, random_state=0)
    tprobs, kept = predict(list(test["abs"]), mode)
    ty = test["role"].to_numpy()[kept]
    tpf, tpr = role_probs(tprobs, classes)
    with_unc = metrics(ty, decide_all(tpf, tpr, th["t_fresh"], th["t_rotten"]))
    argmax = metrics(ty, np.array([class_role(classes[i]) for i in tprobs.argmax(axis=1)], dtype=object))
    report["test_metrics"] = {"with_uncertain_option": with_unc, "plain_argmax": argmax, "n": int(len(kept))}
    print("TEST (plain argmax):", json.dumps(argmax, indent=1))
    print("TEST (with 'uncertain' thresholds):", json.dumps(with_unc, indent=1))
    rep = BACKEND_DIR / "reports" / f"condition_eval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    rep.parent.mkdir(exist_ok=True)
    rep.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Report:", rep)
    if a.install:
        dest = BACKEND_DIR / "models" / "production" / "condition"
        dest.mkdir(parents=True, exist_ok=True)
        cfg = {"model_file": str(model_path.resolve()), "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
               "class_names": classes, "input_size": size, "preprocessing": mode, "t_fresh": th["t_fresh"], "t_rotten": th["t_rotten"],
               "target_precision": th["target_precision"], "test_metrics": report["test_metrics"], "evaluated": report["time"],
               "report": str(rep)}
        (dest / "condition_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print("Installed:", dest / "condition_config.json", "(restart the backend)")


if __name__ == "__main__":
    main()
