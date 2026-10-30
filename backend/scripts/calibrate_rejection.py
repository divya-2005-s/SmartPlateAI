"""
SmartPlateAI - calibrate non-food / low-confidence rejection for a trained food model (READ-ONLY on datasets).

Writes into the model folder:  rejection_config.json, rejection_stats.npz   (+ reports\\rejection\\<run>\\rejection_report.md)

Data roles (never mixed):
  statistics  : up to --per-class TRAIN images per food (class means + covariance for the feature-distance signal)
  calibration : half of the VALIDATION images (+ half of the non-food images)  -> thresholds are chosen here
  evaluation  : the other half of each                                          -> reported rates
  test        : only with --confirm-final-test, once                            -> final false-rejection check on held-out foods
Non-food images: data_nonfood\\general, data_nonfood\\hard (your own photos) and a random sample of the OCR packaging images (--packaging-dir).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))
from app.ml.recognizer import IMAGENET_FOOD_INDICES, FoodRecognizer, decode_upload, sha256_file  # noqa: E402
from app.ml.rejection import (Thresholds, choose_conf_margin, choose_gate_thresholds, decide_batch,  # noqa: E402
                              fit_feature_stats, min_mahalanobis, wilson_interval)
from train_food_classifier import class_names_from_manifest, load_manifest  # noqa: E402

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
LIMITATIONS = [
    "Non-food rejection was only evaluated on the negative examples listed above. Categories or conditions not represented there are untested.",
    "Food that is not one of the 24 supported foods (sushi, curry, ...) may be answered with UNSUPPORTED_FOOD or LOW_CONFIDENCE, not a food name.",
    "Packaging photos, empty plates and food drawings can look food-like to the ImageNet signal; see the 'hard' and 'packaging' rows.",
    "Thresholds guarantee nothing for a single photo; rates are estimates from finite samples (95% Wilson intervals shown).",
]


def half(key: str) -> int:
    return zlib.crc32(key.encode("utf-8")) % 2  # 0 = calibration half, 1 = evaluation half (deterministic)


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMG_EXT) if folder.is_dir() else []


def embed_paths(rec, paths: list[str], batch: int = 32, workers: int = 4, label: str = ""):
    """Same decode/resize/model path as the API. Returns (ok_mask, probs, feats, food_mass) for the readable images."""
    ok = np.zeros(len(paths), bool)
    P, F, M = [], [], []

    def load(p):
        try:
            return decode_upload(Path(p).read_bytes())
        except Exception:  # noqa: BLE001
            return None

    t0 = time.time()
    with ThreadPoolExecutor(workers) as pool:
        for start in range(0, len(paths), batch):
            imgs = list(pool.map(load, paths[start:start + batch]))
            idx = [i for i, im in enumerate(imgs) if im is not None]
            if idx:
                p, f, m = rec.embed(np.stack([rec.prepare(imgs[i]) for i in idx]))
                P.append(p); F.append(f); M.append(m)
                ok[[start + i for i in idx]] = True
            if (start // batch) % 25 == 0:
                done = min(start + batch, len(paths))
                print(f"  [{label}] {done:,}/{len(paths):,} ({done / max(time.time() - t0, 1e-6):.1f} img/s)", flush=True)
    empty = np.zeros((0,))
    return ok, (np.concatenate(P) if P else empty), (np.concatenate(F) if F else empty), (np.concatenate(M) if M else empty)


def rate(k: int, n: int) -> str:
    lo, hi = wilson_interval(k, n)
    return f"{k}/{n} = {k / n:.1%} (95% CI {lo:.1%}-{hi:.1%})" if n else "n/a (no images)"


def summarise_positives(decisions: np.ndarray, correct: np.ndarray) -> dict:
    n = len(decisions)
    acc_mask = decisions == "accept"
    return {"n": n, "accepted": int(acc_mask.sum()),
            **{f"{d}": int((decisions == d).sum()) for d in ("non_food", "unsupported_food", "uncertain")},
            "accuracy_of_accepted": float(correct[acc_mask].mean()) if acc_mask.any() else None,
            "accuracy_all_images": float(correct.mean()) if n else None}


def main() -> int:
    ap = argparse.ArgumentParser(description="Calibrate non-food rejection.")
    ap.add_argument("--model-dir", required=True, help="Run folder containing best.keras and class_names.json")
    ap.add_argument("--nonfood-dir", default=str(BACKEND_DIR / "data_nonfood"))
    ap.add_argument("--packaging-dir", help="OCR dataset folder; a random sample is used as 'packaging' negatives")
    ap.add_argument("--packaging-n", type=int, default=400)
    ap.add_argument("--per-class", type=int, default=300)
    ap.add_argument("--target-accuracy", type=float, default=0.95)
    ap.add_argument("--max-false-reject", type=float, default=0.02)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--confirm-final-test", action="store_true")
    args = ap.parse_args()

    model_dir = Path(args.model_dir)
    if args.confirm_final_test and (model_dir / "rejection_test_eval.json").exists():
        print("ERROR: the test split was already used for this model's rejection evaluation. Not repeating it.")
        return 1
    rec = FoodRecognizer(model_dir, allow_uncalibrated=True)
    if not rec.load():
        print(f"ERROR: {rec.status_message}")
        return 1
    df = load_manifest()
    names = class_names_from_manifest(df)
    if names != rec.class_names:
        print("ERROR: class order in the model folder differs from the manifest.")
        return 1
    K = len(names)
    out_dir = BACKEND_DIR / "reports" / "rejection" / model_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- statistics subset (train originals preferred)
    tr = df[df.new_split == "train"]
    pool = tr[~tr.is_augmented_copy]
    pool = pool if pool.class_id.nunique() == K else tr
    sub = pd.concat([g.sample(n=min(args.per_class, len(g)), random_state=args.seed) for _, g in pool.groupby("class_id")])
    print(f"Fitting feature statistics on {len(sub):,} training images ...")
    ok, p_tr, f_tr, _ = embed_paths(rec, sub.image_path.astype(str).tolist(), args.batch_size, label="train-stats")
    means, precision = fit_feature_stats(f_tr, sub.class_id.to_numpy()[ok], K)

    # ---- validation positives
    val = df[df.new_split == "val"].reset_index(drop=True)
    ok, p_v, f_v, m_v = embed_paths(rec, val.image_path.astype(str).tolist(), args.batch_size, label="validation")
    val = val[ok].reset_index(drop=True)
    d_v = min_mahalanobis(f_v, means, precision)
    y_v, pred_v = val.class_id.to_numpy(), p_v.argmax(1)
    correct_v = pred_v == y_v
    cal_v = np.array([half(i) == 0 for i in val.image_id.astype(str)])

    # ---- negatives
    neg_paths: dict[str, list[str]] = {}
    root = Path(args.nonfood_dir)
    for cat in ("general", "hard"):
        neg_paths[cat] = [str(p) for p in list_images(root / cat)]
    if args.packaging_dir:
        allp = list_images(Path(args.packaging_dir))
        rng = np.random.default_rng(args.seed)
        pick = rng.choice(len(allp), size=min(args.packaging_n, len(allp)), replace=False) if allp else []
        neg_paths["packaging"] = [str(allp[i]) for i in sorted(pick)]
    negs: dict[str, dict] = {}
    for cat, paths in neg_paths.items():
        if not paths:
            continue
        ok_n, p_n, f_n, m_n = embed_paths(rec, paths, args.batch_size, label=f"non-food:{cat}")
        kept = [p for p, o in zip(paths, ok_n) if o]
        negs[cat] = {"paths": kept, "probs": p_n, "fm": m_n, "d": min_mahalanobis(f_n, means, precision) if len(kept) else np.zeros(0),
                     "half": np.array([half(Path(p).name) for p in kept])}
    n_neg_total = sum(len(v["paths"]) for v in negs.values())
    if len(negs.get("general", {}).get("paths", [])) < 100:
        print("WARNING: fewer than 100 general non-food photos in data_nonfood\\general - general non-food rejection cannot be established yet.")
    print(f"Non-food images readable: { {k: len(v['paths']) for k, v in negs.items()} }")

    # ---- thresholds from the CALIBRATION halves only
    cal_neg_fm = np.concatenate([v["fm"][v["half"] == 0] for v in negs.values()]) if negs else np.zeros(0)
    cal_neg_d = np.concatenate([v["d"][v["half"] == 0] for v in negs.values()]) if negs else np.zeros(0)
    gate = choose_gate_thresholds(m_v[cal_v], d_v[cal_v], cal_neg_fm, cal_neg_d, args.max_false_reject)
    passed = cal_v & (d_v <= gate["maha_high"])
    srt = np.sort(p_v, axis=1)
    cm = choose_conf_margin(srt[:, -1][passed], (srt[:, -1] - srt[:, -2])[passed], correct_v[passed], args.target_accuracy)
    th = Thresholds(gate["food_mass_low"], gate["maha_high"], cm["conf_min"], cm["margin_min"])
    with_neg = gate["neg_reject_calib"] is not None
    print(f"Thresholds: {asdict(th)}  (negatives used for calibration: {with_neg})")

    # ---- evaluation halves
    def decide(p, d, fm):
        return decide_batch(p, d, fm, th)

    ev = ~cal_v
    pos_eval = summarise_positives(decide(p_v[ev], d_v[ev], m_v[ev]), correct_v[ev])
    pos_cal = summarise_positives(decide(p_v[cal_v], d_v[cal_v], m_v[cal_v]), correct_v[cal_v])
    neg_eval = {}
    for cat, v in negs.items():
        sel = v["half"] == 1
        dec = decide(v["probs"][sel], v["d"][sel], v["fm"][sel]) if sel.any() else np.array([])
        neg_eval[cat] = {"n": int(sel.sum()), "non_food": int((dec == "non_food").sum()), "not_accepted": int((dec != "accept").sum()),
                         "accepted_as_food": int((dec == "accept").sum())}

    test_eval = None
    if args.confirm_final_test:
        flag = model_dir / "rejection_test_eval.json"
        te = df[df.new_split == "test"].reset_index(drop=True)
        ok_t, p_t, f_t, m_t = embed_paths(rec, te.image_path.astype(str).tolist(), args.batch_size, label="test")
        te = te[ok_t]
        dec_t = decide(p_t, min_mahalanobis(f_t, means, precision), m_t)
        ok_orig = ~te.is_augmented_copy.to_numpy()
        test_eval = {"all": summarise_positives(dec_t, p_t.argmax(1) == te.class_id.to_numpy()),
                     "original_only": summarise_positives(dec_t[ok_orig], (p_t.argmax(1) == te.class_id.to_numpy())[ok_orig])}
        flag.write_text(json.dumps(test_eval, indent=2), encoding="utf-8")

    # ---- save config + stats
    np.savez_compressed(model_dir / "rejection_stats.npz", means=means, precision=precision)
    cfg = {"version": 1, "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "source_run": model_dir.name,
           "model_sha256": sha256_file(model_dir / "best.keras"), "input_size": rec.size, "feature_dim": int(means.shape[1]),
           "imagenet_food_indices": IMAGENET_FOOD_INDICES, "thresholds": asdict(th), "calibrated_with_negatives": with_neg,
           "calibration": {"gate": gate, "confidence_margin": cm, "target_accuracy": args.target_accuracy, "max_false_reject": args.max_false_reject,
                           "n_valid_food_calibration": int(cal_v.sum()), "n_non_food_calibration": int(len(cal_neg_fm)),
                           "non_food_images_by_category": {k: len(v["paths"]) for k, v in negs.items()}},
           "evaluation": {"valid_food_eval_half": pos_eval, "non_food_eval_half": neg_eval, "test_final": test_eval},
           "limitations": LIMITATIONS}
    (model_dir / "rejection_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # ---- report
    L = ["# Non-food rejection calibration report", "", f"Model run: `{model_dir.name}` | generated {cfg['created']} | seed {args.seed}", "",
         "## Thresholds", "", "```json", json.dumps(asdict(th), indent=2), "```", "",
         f"Gate method: {gate['method']}. Confidence/margin: target accuracy of accepted predictions {args.target_accuracy:.0%} "
         f"({'met' if cm['target_met'] else 'NOT met - best available chosen'}); coverage on calibration data "
         f"{cm['coverage'] if cm['coverage'] is None else round(cm['coverage'], 3)}.", "",
         "## Valid foods (validation, evaluation half - not used to choose thresholds)", ""]
    n = pos_eval["n"]
    L += [f"- images: {n:,}", f"- accepted: {rate(pos_eval['accepted'], n)}",
          f"- wrongly rejected as NON_FOOD: {rate(pos_eval['non_food'], n)}",
          f"- UNSUPPORTED_FOOD: {rate(pos_eval['unsupported_food'], n)}", f"- LOW_CONFIDENCE: {rate(pos_eval['uncertain'], n)}",
          f"- accuracy among accepted: {pos_eval['accuracy_of_accepted']}", f"- accuracy over all images (no rejection): {pos_eval['accuracy_all_images']}", "",
          "## Non-food images (evaluation half)", ""]
    if not neg_eval:
        L += ["**No non-food images were supplied. Rejection thresholds are positive-only percentiles; the non-food rejection rate is UNKNOWN "
              "and must not be claimed.** Put non-food photos in data_nonfood\\general and data_nonfood\\hard, then re-run.", ""]
    for cat, r in neg_eval.items():
        flag = "  **(too few images to draw conclusions)**" if r["n"] < 100 else ""
        L += [f"- **{cat}** (n={r['n']}){flag}: rejected as NON_FOOD {rate(r['non_food'], r['n'])}; not accepted as a food (any rejection) "
              f"{rate(r['not_accepted'], r['n'])}; wrongly accepted as food {rate(r['accepted_as_food'], r['n'])}"]
    if test_eval:
        L += ["", "## Held-out test foods (final check, used once)", "", f"- all: {test_eval['all']}", f"- original images only: {test_eval['original_only']}"]
    L += ["", "## Limitations", ""] + [f"- {x}" for x in LIMITATIONS]
    (out_dir / "rejection_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\nWrote {model_dir / 'rejection_config.json'}\nReport: {out_dir / 'rejection_report.md'}")
    print(f"Valid foods (eval half): accepted {rate(pos_eval['accepted'], n)}; wrongly NON_FOOD {rate(pos_eval['non_food'], n)}")
    for cat, r in neg_eval.items():
        print(f"Non-food/{cat}: NON_FOOD {rate(r['non_food'], r['n'])}; wrongly accepted {rate(r['accepted_as_food'], r['n'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())