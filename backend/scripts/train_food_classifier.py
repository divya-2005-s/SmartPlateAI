"""
SmartPlateAI - Phase 4: MobileNetV2 food classifier (transfer learning, CPU-friendly).

Uses the Phase 3 split manifest AS IS (data_prep\\split_manifest.csv, column `new_split`); it never creates a split.
Freshness is NOT handled here. Test data is only touched with --confirm-final-test.

Stages
  --validate-only                      check manifest, class weights, image paths, sample decode. No training.
  (default) --stage head               frozen MobileNetV2 backbone + new softmax head (use --max-*-per-class for a pilot)
  --stage finetune --init-model PATH   unfreeze only the last N backbone layers (BatchNorm stays frozen), low learning rate
  --evaluate-only --model-path PATH    evaluate a saved model on val (or test with --confirm-final-test)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

BACKEND_DIR = Path(__file__).resolve().parents[1]
MANIFEST = BACKEND_DIR / "data_prep" / "split_manifest.csv"
WEIGHTS_JSON = BACKEND_DIR / "reports" / "phase3" / "class_weights.json"
MODELS_DIR = BACKEND_DIR / "models"
TRAIN_REPORTS = BACKEND_DIR / "reports" / "training"
SPLITS = ("train", "val", "test")
REQUIRED_COLS = ["image_id", "image_name", "image_path", "food", "class_id", "source_dataset", "new_split",
                 "group_id", "is_augmented_copy"]
VALID_SIZES = (96, 128, 160, 192, 224)


# ----------------------------------------------------------------------------- generic helpers
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md_table(df: pd.DataFrame, max_rows: int = 40) -> str:
    if df is None or len(df) == 0:
        return "_(none)_\n"
    d = df.head(max_rows).copy().astype(object)
    d = d.where(d.notna(), "")
    cols = [str(c) for c in d.columns]
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, r in d.iterrows():
        out.append("| " + " | ".join(str(v).replace("|", "\\|") for v in r) + " |")
    return "\n".join(out) + "\n"


def log(msg: str) -> None:
    print(msg, flush=True)


# ----------------------------------------------------------------------------- manifest + class weights
def load_manifest() -> pd.DataFrame:
    if not MANIFEST.is_file():
        raise SystemExit(f"ERROR: manifest not found: {MANIFEST}\nRun Phase 3 (scripts\\prepare_splits.py) first.")
    df = pd.read_csv(MANIFEST, dtype={"image_id": str, "sha256": str, "dhash": str}, low_memory=False)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise SystemExit(f"ERROR: manifest is missing required columns: {missing}\nFound columns: {list(df.columns)}")
    df["is_augmented_copy"] = df["is_augmented_copy"].astype(str).str.lower().eq("true")
    df["class_id"] = df["class_id"].astype(int)
    return df


def validate_manifest(df: pd.DataFrame, expected_classes: int, check_paths: bool = True) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    info: list[str] = []
    info.append(f"rows: {len(df):,}")
    bad_split = ~df["new_split"].isin(SPLITS)
    if bad_split.any():
        errors.append(f"{int(bad_split.sum())} rows have a new_split outside {SPLITS}: {sorted(df.loc[bad_split, 'new_split'].astype(str).unique())[:5]}")
    info.append("split counts: " + ", ".join(f"{s}={int((df.new_split == s).sum()):,}" for s in SPLITS))
    if df["image_id"].duplicated().any():
        errors.append(f"{int(df['image_id'].duplicated().sum())} duplicate image_id values")
    if df["image_path"].isna().any() or (df["image_path"].astype(str).str.strip() == "").any():
        errors.append("some rows have an empty image_path")
    pairs = df[["class_id", "food"]].drop_duplicates()
    if pairs["class_id"].duplicated().any() or pairs["food"].duplicated().any():
        errors.append("class_id <-> food is not one-to-one in the manifest")
    ids = sorted(df["class_id"].unique())
    if ids != list(range(len(ids))):
        errors.append(f"class_id values are not contiguous 0..K-1: {ids[:10]}...")
    if len(ids) != expected_classes:
        errors.append(f"found {len(ids)} classes, expected {expected_classes} (--expected-classes)")
    info.append(f"classes: {len(ids)}")
    g = df.groupby("group_id")["new_split"].nunique()
    if (g > 1).any():
        errors.append(f"{int((g > 1).sum())} group_id values cross splits - the split is not leakage-safe; do not train")
    if "sha256" in df.columns:
        s = df[df["sha256"].fillna("").astype(str) != ""].groupby("sha256")["new_split"].nunique()
        if (s > 1).any():
            errors.append(f"{int((s > 1).sum())} byte-identical images cross splits")
    ct = pd.crosstab(df["class_id"], df["new_split"]).reindex(columns=list(SPLITS), fill_value=0)
    thin = ct[(ct < 20).any(axis=1)]
    if len(thin):
        warnings.append(f"classes with fewer than 20 images in some split: {thin.index.tolist()}")
    if check_paths:
        exists = np.array([os.path.isfile(p) for p in df["image_path"].astype(str)])
        info.append(f"image files found: {int(exists.sum()):,} of {len(df):,}")
        if not exists.all():
            miss = df.loc[~exists, "image_path"].astype(str).head(3).tolist()
            errors.append(f"{int((~exists).sum())} image files not found, e.g. {miss}")
    return errors, warnings, info


def class_names_from_manifest(df: pd.DataFrame) -> list[str]:
    m = df[["class_id", "food"]].drop_duplicates().sort_values("class_id")
    return m["food"].astype(str).tolist()


def load_class_weights(class_names: list[str], n_train: int) -> tuple[np.ndarray, dict]:
    if not WEIGHTS_JSON.is_file():
        raise SystemExit(f"ERROR: class weight file not found: {WEIGHTS_JSON}")
    j = json.loads(WEIGHTS_JSON.read_text(encoding="utf-8"))
    for key in ("class_names_in_class_id_order", "weights"):
        if key not in j:
            raise SystemExit(f"ERROR: {WEIGHTS_JSON.name} has no '{key}'. Keys present: {list(j)}")
    if list(j["class_names_in_class_id_order"]) != class_names:
        raise SystemExit("ERROR: class order in class_weights.json differs from the manifest class_id order.\n"
                         f"  json    : {j['class_names_in_class_id_order'][:5]}...\n  manifest: {class_names[:5]}...")
    w = j["weights"]
    k = len(class_names)
    if isinstance(w, dict):
        if set(w) == set(class_names):
            vec = [w[n] for n in class_names]
        elif set(w) == {str(i) for i in range(k)}:
            vec = [w[str(i)] for i in range(k)]
        else:
            raise SystemExit(f"ERROR: 'weights' keys match neither class names nor class ids: {list(w)[:5]}...")
    elif isinstance(w, list) and len(w) == k:
        vec = list(w)
    else:
        raise SystemExit(f"ERROR: unsupported 'weights' structure ({type(w).__name__}).")
    vec = np.array(vec, dtype=np.float64)
    if not np.isfinite(vec).all() or (vec <= 0).any():
        raise SystemExit("ERROR: class weights must all be finite and > 0.")
    meta = {"n_train_in_json": j.get("n_train"), "formula": j.get("formula")}
    if j.get("n_train") not in (None, n_train):
        log(f"WARNING: class_weights.json was computed for n_train={j.get('n_train')} but the manifest train split has {n_train}.")
    return vec, meta


def weights_from_counts(counts: np.ndarray) -> np.ndarray:
    k = len(counts)
    return counts.sum() / (k * np.maximum(counts, 1))


def subset_per_class(df: pd.DataFrame, cap: int, seed: int) -> pd.DataFrame:
    if cap <= 0:
        return df
    parts = [g.sample(n=min(cap, len(g)), random_state=seed) for _, g in df.groupby("class_id")]
    return pd.concat(parts).sort_index()


# ----------------------------------------------------------------------------- metrics (numpy only)
def compute_metrics(y_true: np.ndarray, probs: np.ndarray) -> dict:
    k = probs.shape[1]
    y_pred = probs.argmax(axis=1)
    cm = np.zeros((k, k), dtype=np.int64)
    np.add.at(cm, (y_true, y_pred), 1)
    tp = np.diag(cm).astype(float)
    support = cm.sum(axis=1).astype(float)
    pred_n = cm.sum(axis=0).astype(float)
    prec = np.divide(tp, pred_n, out=np.zeros(k), where=pred_n > 0)
    rec = np.divide(tp, support, out=np.zeros(k), where=support > 0)
    f1 = np.divide(2 * prec * rec, prec + rec, out=np.zeros(k), where=(prec + rec) > 0)
    present = support > 0
    top3 = np.argsort(-probs, axis=1)[:, :3]
    eps = 1e-12
    return {
        "n": int(len(y_true)), "accuracy": float((y_pred == y_true).mean()),
        "top3_accuracy": float((top3 == y_true[:, None]).any(axis=1).mean()),
        "macro_precision": float(prec[present].mean()), "macro_recall": float(rec[present].mean()),
        "macro_f1": float(f1[present].mean()),
        "weighted_f1": float((f1 * support).sum() / support.sum()),
        "log_loss": float(-np.log(probs[np.arange(len(y_true)), y_true] + eps).mean()),
        "mean_top1_confidence": float(probs.max(axis=1).mean()),
        "_cm": cm, "_prec": prec, "_rec": rec, "_f1": f1, "_support": support,
    }


def top_confusions(cm: np.ndarray, names: list[str], n: int = 10) -> pd.DataFrame:
    off = cm.copy()
    np.fill_diagonal(off, 0)
    idx = np.dstack(np.unravel_index(np.argsort(-off, axis=None)[:n], off.shape))[0]
    rows = [{"true": names[i], "predicted_as": names[j], "images": int(off[i, j])} for i, j in idx if off[i, j] > 0]
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- TensorFlow pieces (imported lazily)
def import_tf(cpu_threads: int):
    import tensorflow as tf  # noqa: PLC0415
    if cpu_threads > 0:
        tf.config.threading.set_intra_op_parallelism_threads(cpu_threads)
        tf.config.threading.set_inter_op_parallelism_threads(max(1, min(2, cpu_threads)))
    return tf


def tf_decode_ok(tf, path: str) -> bool:
    try:
        img = tf.io.decode_image(tf.io.read_file(path), channels=3, expand_animations=False)
        return len(img.shape) == 3 and int(img.shape[0]) > 0 and int(img.shape[1]) > 0
    except Exception:  # noqa: BLE001
        return False


def precheck_decode(tf, df: pd.DataFrame, workers: int = 4) -> pd.DataFrame:
    """Decode every selected image with the SAME TensorFlow decoder used in training. Results are cached."""
    cache_path = TRAIN_REPORTS / "decode_check_cache.csv"
    ok_ids: set[str] = set()
    if cache_path.is_file():
        c = pd.read_csv(cache_path, dtype={"image_id": str})
        ok_ids = set(c.loc[c["ok"].astype(bool), "image_id"])
    todo = df[~df["image_id"].isin(ok_ids)]
    log(f"Decode pre-check: {len(df) - len(todo):,} images already verified (cache), checking {len(todo):,} ...")
    results: list[tuple[str, bool]] = []
    if len(todo):
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, (iid, ok) in enumerate(zip(todo["image_id"], pool.map(lambda p: tf_decode_ok(tf, p), todo["image_path"].astype(str))), 1):
                results.append((iid, ok))
                if i % 2000 == 0:
                    log(f"  checked {i:,}/{len(todo):,} ({i / (time.time() - t0):.0f}/s)")
        new = pd.DataFrame(results, columns=["image_id", "ok"])
        if cache_path.is_file():
            old = pd.read_csv(cache_path, dtype={"image_id": str})
            new = pd.concat([old[~old["image_id"].isin(new["image_id"])], new])
        TRAIN_REPORTS.mkdir(parents=True, exist_ok=True)
        new.to_csv(cache_path, index=False)
    bad_ids = {iid for iid, ok in results if not ok}
    return df[df["image_id"].isin(bad_ids)]


def make_dataset(tf, df: pd.DataFrame, size: int, batch: int, training: bool, seed: int, class_weights: np.ndarray | None):
    paths = tf.constant(df["image_path"].astype(str).tolist())
    labels = tf.constant(df["class_id"].to_numpy(np.int32))
    ds = tf.data.Dataset.from_tensor_slices((paths, labels))
    if training:
        ds = ds.shuffle(len(df), seed=seed, reshuffle_each_iteration=True)  # shuffles paths only, not pixels

    def load(path, label):
        img = tf.io.decode_image(tf.io.read_file(path), channels=3, expand_animations=False)
        img.set_shape([None, None, 3])
        img = tf.image.resize(img, [size, size], method="bilinear", antialias=True)  # float32, values 0..255
        return img, label

    ds = ds.map(load, num_parallel_calls=tf.data.AUTOTUNE, deterministic=True)
    if training and class_weights is not None:
        w = tf.constant(class_weights, dtype=tf.float32)
        ds = ds.map(lambda x, y: (x, y, tf.gather(w, y)), num_parallel_calls=tf.data.AUTOTUNE, deterministic=True)
    return ds.batch(batch).prefetch(tf.data.AUTOTUNE)


def build_model(tf, num_classes: int, size: int, dropout: float):
    keras = tf.keras
    inputs = keras.Input(shape=(size, size, 3), name="image")          # raw RGB, float 0..255
    x = keras.Sequential([
        keras.layers.RandomFlip("horizontal"), keras.layers.RandomRotation(0.05),
        keras.layers.RandomZoom(0.1), keras.layers.RandomContrast(0.1)], name="augmentation")(inputs)  # active only in training
    x = keras.layers.Rescaling(1.0 / 127.5, offset=-1.0, name="mobilenetv2_preprocess")(x)             # == mobilenet_v2.preprocess_input
    base = keras.applications.MobileNetV2(input_shape=(size, size, 3), include_top=False, weights="imagenet")
    base.trainable = False
    x = base(x, training=False)
    x = keras.layers.GlobalAveragePooling2D()(x)
    x = keras.layers.Dropout(dropout)(x)
    outputs = keras.layers.Dense(num_classes, activation="softmax", name="food_probs")(x)
    return keras.Model(inputs, outputs, name="smartplate_food_mnv2")


def find_backbone(tf, model):
    for layer in model.layers:
        if isinstance(layer, tf.keras.Model) and layer.name.lower().startswith("mobilenet"):
            return layer
    raise SystemExit("ERROR: could not find the MobileNetV2 backbone inside the loaded model.")


def prepare_finetune(tf, model, unfreeze_last: int) -> dict:
    backbone = find_backbone(tf, model)
    backbone.trainable = True
    n = len(backbone.layers)
    for i, layer in enumerate(backbone.layers):
        layer.trainable = (i >= n - unfreeze_last) and not isinstance(layer, tf.keras.layers.BatchNormalization)
    trainable = int(sum(int(np.prod(w.shape)) for w in model.trainable_weights))
    return {"backbone_layers": n, "unfrozen_last_n": unfreeze_last, "trainable_parameters": trainable}


def compile_model(tf, model, lr: float) -> None:
    model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=lr),
                  loss=tf.keras.losses.SparseCategoricalCrossentropy(),
                  metrics=[tf.keras.metrics.SparseCategoricalAccuracy(name="accuracy")])


# ----------------------------------------------------------------------------- evaluation
def evaluate_model(tf, model, df_split: pd.DataFrame, split: str, names: list[str], out_dir: Path, args) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.skip_decode_precheck:
        bad = precheck_decode(tf, df_split)
        if len(bad):
            if not args.drop_undecodable:
                raise SystemExit(f"ERROR: {len(bad)} {split} images cannot be decoded by TensorFlow: "
                                 f"{bad['image_path'].head(3).tolist()}")
            bad_ids = set(bad["image_id"])
            df_split = df_split[~df_split["image_id"].isin(bad_ids)].copy()
            log(f"Dropped {len(bad_ids)} undecodable images from {split} evaluation.")
    if df_split.empty:
        raise SystemExit(f"ERROR: no decodable images remain in the {split} split for evaluation.")
    ds = make_dataset(tf, df_split, args.image_size, args.batch_size, training=False, seed=args.seed, class_weights=None)
    probs = model.predict(ds, verbose=1)
    if probs.shape != (len(df_split), len(names)):
        raise SystemExit(f"ERROR: prediction shape {probs.shape} != ({len(df_split)}, {len(names)})")
    y_true = df_split["class_id"].to_numpy()
    top1 = probs.argmax(axis=1)
    pred = pd.DataFrame({
        "image_id": df_split["image_id"].values, "true_id": y_true, "true_food": df_split["food"].values,
        "pred_id": top1, "pred_food": [names[i] for i in top1], "top1_confidence": probs.max(axis=1).round(4),
        "correct": top1 == y_true, "is_augmented_copy": df_split["is_augmented_copy"].values,
        "source_dataset": df_split["source_dataset"].values})
    pred.to_csv(out_dir / f"predictions_{split}.csv", index=False)
    pred[~pred.correct].sort_values("top1_confidence", ascending=False).head(300).to_csv(
        out_dir / f"misclassified_{split}.csv", index=False)
    results: dict = {"split": split, "subsets": {}}
    masks = {"all": np.ones(len(df_split), bool), "original_only": ~df_split["is_augmented_copy"].to_numpy()}
    for name, mask in masks.items():
        if mask.sum() == 0:
            continue
        m = compute_metrics(y_true[mask], probs[mask])
        per_class = pd.DataFrame({"class_id": range(len(names)), "food": names, "support": m["_support"].astype(int),
                                  "precision": m["_prec"].round(4), "recall": m["_rec"].round(4), "f1": m["_f1"].round(4)})
        per_class.to_csv(out_dir / f"per_class_{split}_{name}.csv", index=False)
        pd.DataFrame(m["_cm"], index=[f"true_{n}" for n in names], columns=[f"pred_{n}" for n in names]).to_csv(
            out_dir / f"confusion_matrix_{split}_{name}.csv")
        results["subsets"][name] = {k: v for k, v in m.items() if not k.startswith("_")}
        results["subsets"][name]["top_confusions"] = top_confusions(m["_cm"], names).to_dict("records")
        results["subsets"][name]["_per_class_df"] = per_class
    slim = {k: ({n: {kk: vv for kk, vv in s.items() if kk != "_per_class_df"} for n, s in v.items()} if k == "subsets" else v)
            for k, v in results.items()}
    (out_dir / f"evaluation_{split}.json").write_text(json.dumps(slim, indent=2), encoding="utf-8")
    return results


def log_test_evaluation(model_path: Path, res: dict) -> int:
    TRAIN_REPORTS.mkdir(parents=True, exist_ok=True)
    f = TRAIN_REPORTS / "test_evaluations.csv"
    prior = len(pd.read_csv(f)) if f.is_file() else 0
    a = res["subsets"]["all"]
    row = pd.DataFrame([{"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "model": str(model_path),
                         "n": a["n"], "accuracy": round(a["accuracy"], 4), "macro_f1": round(a["macro_f1"], 4)}])
    row.to_csv(f, mode="a", header=not f.is_file(), index=False)
    return prior


# ----------------------------------------------------------------------------- report
LIMITATIONS = """\
- The model only knows the 24 foods in the dataset. Any other food, a drink, an empty plate or a non-food photo is still forced into one of
  the 24 classes: it has no "other / not food" class. A softmax score is not a probability that the answer is correct.
- Images come from three public image sources. Fast-food classes come from one source and most fruit/vegetable classes from one
  source each, so the model can partly learn each source's photo style. Expect lower accuracy on your own phone photos.
- Apple, banana and orange include pre-augmented copies (rotated/shifted). Headline metrics should use the `original_only` subset.
- Near-duplicate detection in Phase 3 cannot catch rotated or cropped copies of the same photo, so small residual leakage is possible.
- Class imbalance is handled with class weights only; per-class recall matters more than overall accuracy.
- Freshness is not predicted by this model.
"""


def write_report(out_dir: Path, cfg: dict, train_counts: pd.DataFrame, val_res: dict | None, test_res: dict | None) -> None:
    L = ["# SmartPlateAI - Phase 4 Training Report", "",
         f"Run: `{cfg['run_name']}` | stage: {cfg['stage']} | generated {cfg['generated']}", "",
         "## Configuration", "", "```json", json.dumps({k: cfg[k] for k in (
             "stage", "image_size", "batch_size", "epochs_requested", "epochs_run", "learning_rate", "seed", "subset_caps",
             "class_weight_source", "train_images", "val_images", "train_seconds", "train_images_per_second", "finetune")}, indent=2), "```", "",
         "## Class imbalance (training images used) and weights", "", md_table(train_counts, 40)]

    def section(title: str, res: dict | None) -> None:
        if not res:
            return
        L.extend([f"## {title}", ""])
        for name, s in res["subsets"].items():
            L.extend([f"### Subset: {name} (n={s['n']:,})", "",
                      f"accuracy {s['accuracy']:.4f} | macro precision {s['macro_precision']:.4f} | macro recall {s['macro_recall']:.4f} | "
                      f"macro F1 {s['macro_f1']:.4f} | weighted F1 {s['weighted_f1']:.4f} | top-3 {s['top3_accuracy']:.4f} | log loss {s['log_loss']:.4f}", ""])
            pc = s["_per_class_df"].sort_values("f1")
            L.extend(["Weakest 8 classes by F1:", "", md_table(pc.head(8)), "Most frequent confusions:", "", md_table(pd.DataFrame(s["top_confusions"])), ""])
    section("Validation results (best checkpoint; validation data guided checkpoint selection)", val_res)
    section("Test results (held-out; evaluated once, not used for tuning)", test_res)
    if not test_res:
        L.extend(["## Test set", "", "Not evaluated in this run (by design).", ""])
    L.extend(["## Limitations", "", LIMITATIONS])
    (out_dir / "training_report.md").write_text("\n".join(L), encoding="utf-8")


# ----------------------------------------------------------------------------- modes
def run_validate_only(df: pd.DataFrame, names: list[str], args) -> int:
    errors, warnings, info = validate_manifest(df, args.expected_classes, check_paths=True)
    w_vec = None
    try:
        w_vec, _ = load_class_weights(names, int((df.new_split == "train").sum()))
        info.append(f"class weights: {len(w_vec)} values, min {w_vec.min():.3f}, max {w_vec.max():.3f} (order matches manifest)")
    except SystemExit as exc:
        errors.append(str(exc))
    train_counts = df[df.new_split == "train"]["food"].value_counts()
    info.append(f"train imbalance: {train_counts.max() / train_counts.min():.1f}x (largest {train_counts.max():,} {train_counts.idxmax()}, "
                f"smallest {train_counts.min():,} {train_counts.idxmin()})")
    src = pd.crosstab(df["source_dataset"], df["new_split"]).reindex(columns=list(SPLITS), fill_value=0)
    single = df.groupby("food")["source_dataset"].nunique()
    info.append(f"dataset-source bias: {int((single == 1).sum())} of {len(single)} foods come from a single image source")
    info.append("augmented copies: " + ", ".join(f"{s}={int(df[(df.new_split == s)].is_augmented_copy.sum()):,}" for s in SPLITS))
    # sample decode
    sample = df.sample(n=min(args.sample_check, len(df)), random_state=args.seed)
    from PIL import Image
    pil_bad, fmts = 0, {}
    for p in sample["image_path"].astype(str):
        try:
            with Image.open(p) as im:
                fmts[im.format] = fmts.get(im.format, 0) + 1
                im.convert("RGB").load()
        except Exception:  # noqa: BLE001
            pil_bad += 1
    info.append(f"PIL sample decode: {len(sample) - pil_bad}/{len(sample)} ok, formats {fmts}")
    if pil_bad:
        errors.append(f"{pil_bad} sampled images cannot be decoded by PIL")
    try:
        tf = import_tf(args.cpu_threads)
        tf_bad = sum(not tf_decode_ok(tf, p) for p in sample["image_path"].astype(str))
        info.append(f"TensorFlow {tf.__version__} sample decode: {len(sample) - tf_bad}/{len(sample)} ok; devices: "
                    f"{[d.device_type for d in tf.config.list_physical_devices()]}")
        if tf_bad:
            errors.append(f"{tf_bad} sampled images cannot be decoded by TensorFlow (the training decoder)")
    except ImportError:
        warnings.append("TensorFlow is not importable in this Python; skipped the TensorFlow decode check")
    print("\n================ VALIDATION ================")
    for i in info:
        print("  " + i)
    print("\nImages per source and split:\n" + src.to_string())
    for w in warnings:
        print("WARNING: " + w)
    for e in errors:
        print("ERROR: " + e)
    print("\nVALIDATION " + ("FAILED" if errors else "PASSED") + " (no training was run, no files were written).")
    return 1 if errors else 0


def run_evaluate_only(df: pd.DataFrame, names: list[str], args) -> int:
    if not args.model_path:
        raise SystemExit("ERROR: --evaluate-only needs --model-path")
    model_path = Path(args.model_path)
    if not model_path.is_file():
        raise SystemExit(f"ERROR: model not found: {model_path}")
    if args.split == "test" and not args.confirm_final_test:
        raise SystemExit("ERROR: evaluating the TEST split requires --confirm-final-test (use it once, after all model choices are final).")
    cn = model_path.parent / "class_names.json"
    if cn.is_file() and json.loads(cn.read_text(encoding="utf-8"))["class_names"] != names:
        raise SystemExit("ERROR: class_names.json next to the model does not match the manifest class order.")
    tf = import_tf(args.cpu_threads)
    tf.keras.utils.set_random_seed(args.seed)
    model = tf.keras.models.load_model(str(model_path), compile=False)
    sub = df[df.new_split == args.split]
    out = TRAIN_REPORTS / f"eval_{args.split}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    res = evaluate_model(tf, model, sub, args.split, names, out, args)
    for n, s in res["subsets"].items():
        log(f"[{args.split}/{n}] n={s['n']:,} accuracy={s['accuracy']:.4f} macro_precision={s['macro_precision']:.4f} "
            f"macro_recall={s['macro_recall']:.4f} macro_f1={s['macro_f1']:.4f}")
    if args.split == "test":
        prior = log_test_evaluation(model_path, res)
        log(f"Test set evaluations logged so far (before this one): {prior}. Do not tune the model on test results.")
    log(f"Results written to {out}")
    return 0


def run_training(df: pd.DataFrame, names: list[str], args) -> int:
    k = len(names)
    capped = args.max_train_per_class > 0 or args.max_val_per_class > 0
    if args.confirm_final_test and capped:
        raise SystemExit("ERROR: --confirm-final-test is refused for pilot/capped runs. Finish model selection first, then run\n"
                         "  --evaluate-only --model-path <best.keras> --split test --confirm-final-test")
    if args.stage == "finetune" and not args.init_model:
        raise SystemExit("ERROR: --stage finetune needs --init-model <path to a head-stage best.keras>")
    run_name = args.run_name or f"food_mnv2_{args.stage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    model_dir, rep_dir = MODELS_DIR / run_name, TRAIN_REPORTS / run_name
    if model_dir.exists() or rep_dir.exists():
        raise SystemExit(f"ERROR: run '{run_name}' already exists. Pick another --run-name (nothing is overwritten).")
    tf = import_tf(args.cpu_threads)
    keras = tf.keras
    keras.utils.set_random_seed(args.seed)
    devices = [d.device_type for d in tf.config.list_physical_devices()]
    log(f"TensorFlow {tf.__version__}, devices: {devices}")

    full_train, full_val = df[df.new_split == "train"], df[df.new_split == "val"]
    train = subset_per_class(full_train, args.max_train_per_class, args.seed)
    val = subset_per_class(full_val, args.max_val_per_class, args.seed)
    counts = train["class_id"].value_counts().reindex(range(k), fill_value=0).to_numpy()
    if (counts == 0).any():
        raise SystemExit("ERROR: some classes have no training images in this selection.")
    if args.max_train_per_class > 0:
        weights, wsrc = weights_from_counts(counts.astype(float)), "recomputed from the capped pilot subset (same formula)"
    else:
        weights, _ = load_class_weights(names, len(full_train))
        wsrc = "reports/phase3/class_weights.json"
    log(f"class weights: {wsrc}")

    if not args.skip_decode_precheck:
        bad = precheck_decode(tf, pd.concat([train, val]))
        if len(bad):
            TRAIN_REPORTS.mkdir(parents=True, exist_ok=True)
            bad[["image_id", "image_path", "food"]].to_csv(TRAIN_REPORTS / "decode_failures.csv", index=False)
            if not args.drop_undecodable:
                raise SystemExit(f"ERROR: {len(bad)} selected images cannot be decoded by TensorFlow (list: reports\\training\\decode_failures.csv).\n"
                                 "Fix/remove them, or re-run with --drop-undecodable to exclude them from this run.")
            train, val = train[~train.image_id.isin(bad.image_id)], val[~val.image_id.isin(bad.image_id)]
            log(f"Dropped {len(bad)} undecodable images from this run.")

    lr = args.lr if args.lr else (1e-3 if args.stage == "head" else 1e-5)
    finetune_info = None
    if args.stage == "head" and not args.init_model:
        model = build_model(tf, k, args.image_size, args.dropout)
    else:
        model = keras.models.load_model(str(args.init_model))
        if model.output_shape[-1] != k:
            raise SystemExit(f"ERROR: init model has {model.output_shape[-1]} outputs, expected {k}")
        if args.stage == "head":
            find_backbone(tf, model).trainable = False
            log("restarting head training from the saved checkpoint (optimizer state is not restored)")
        else:
            finetune_info = prepare_finetune(tf, model, args.unfreeze_last)
            log(f"fine-tuning: {finetune_info}")
    compile_model(tf, model, lr)
    log(f"trainable parameters: {int(sum(int(np.prod(w.shape)) for w in model.trainable_weights)):,}")

    train_ds = make_dataset(tf, train, args.image_size, args.batch_size, True, args.seed, weights)
    val_ds = make_dataset(tf, val, args.image_size, args.batch_size, False, args.seed, None)
    model_dir.mkdir(parents=True)
    rep_dir.mkdir(parents=True)
    best_path, final_path = model_dir / "best.keras", model_dir / "final.keras"
    (model_dir / "class_names.json").write_text(json.dumps({
        "class_names": names, "class_id_to_name": {str(i): n for i, n in enumerate(names)},
        "input": {"shape": [args.image_size, args.image_size, 3], "dtype": "float32 RGB 0..255 (preprocessing is inside the model)",
                  "resize": "bilinear, antialias, aspect ratio NOT preserved"}}, indent=2), encoding="utf-8")
    callbacks = [
        keras.callbacks.ModelCheckpoint(str(best_path), monitor="val_loss", save_best_only=True, verbose=1),
        keras.callbacks.EarlyStopping(monitor="val_loss", patience=args.patience, restore_best_weights=True, verbose=1),
        keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=1, min_lr=1e-7, verbose=1),
        keras.callbacks.CSVLogger(str(rep_dir / "history.csv")),
    ]
    log(f"Training {len(train):,} images, validating on {len(val):,}; batch {args.batch_size}, size {args.image_size}, lr {lr}, up to {args.epochs} epochs")
    t0 = time.time()
    hist = model.fit(train_ds, validation_data=val_ds, epochs=args.epochs, callbacks=callbacks, verbose=1)
    secs = time.time() - t0
    epochs_run = len(hist.history["loss"])
    model.save(str(final_path))
    if not best_path.is_file():
        raise SystemExit("ERROR: no best checkpoint was written (training did not finish an epoch).")
    best = keras.models.load_model(str(best_path), compile=False)

    cfg = {"run_name": run_name, "stage": args.stage, "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "image_size": args.image_size, "batch_size": args.batch_size, "epochs_requested": args.epochs, "epochs_run": epochs_run,
           "learning_rate": lr, "seed": args.seed, "dropout": args.dropout, "patience": args.patience,
           "subset_caps": {"train": args.max_train_per_class, "val": args.max_val_per_class},
           "class_weight_source": wsrc, "train_images": len(train), "val_images": len(val),
           "train_seconds": round(secs, 1), "train_images_per_second": round(epochs_run * len(train) / secs, 2),
           "finetune": finetune_info, "init_model": args.init_model,
           "manifest_sha256": sha256_file(MANIFEST), "class_weights_sha256": sha256_file(WEIGHTS_JSON),
           "tensorflow": tf.__version__, "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
           "devices": devices, "determinism_note": "seeds fixed; CPU multi-threading can still cause small run-to-run differences"}
    (rep_dir / "run_config.json").write_text(json.dumps(cfg, indent=2, default=str), encoding="utf-8")

    val_res = evaluate_model(tf, best, val, "val", names, rep_dir, args)
    test_res = None
    if args.confirm_final_test:
        test_res = evaluate_model(tf, best, df[df.new_split == "test"], "test", names, rep_dir, args)
        prior = log_test_evaluation(best_path, test_res)
        log(f"Test evaluations logged before this one: {prior}")
    tc = pd.DataFrame({"food": names, "train_images_used": counts, "class_weight": np.round(weights, 4)})
    write_report(rep_dir, cfg, tc, val_res, test_res)

    log("\n================ TRAINING SUMMARY ================")
    log(f"epochs run: {epochs_run} | speed: {cfg['train_images_per_second']} images/s | time: {secs / 60:.1f} min")
    for n, s in val_res["subsets"].items():
        log(f"[val/{n}] n={s['n']:,} accuracy={s['accuracy']:.4f} macro_precision={s['macro_precision']:.4f} "
            f"macro_recall={s['macro_recall']:.4f} macro_f1={s['macro_f1']:.4f}")
    if test_res:
        for n, s in test_res["subsets"].items():
            log(f"[test/{n}] n={s['n']:,} accuracy={s['accuracy']:.4f} macro_f1={s['macro_f1']:.4f}")
    log(f"Models : {model_dir}\nReports: {rep_dir}\\training_report.md")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="SmartPlateAI Phase 4: MobileNetV2 food classifier.")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--evaluate-only", action="store_true")
    ap.add_argument("--model-path"); ap.add_argument("--split", choices=["val", "test"], default="val")
    ap.add_argument("--confirm-final-test", action="store_true", help="Required to touch the test split. Use once, after model choices are final.")
    ap.add_argument("--stage", choices=["head", "finetune"], default="head")
    ap.add_argument("--init-model", help="Head-stage best.keras to start fine-tuning from.")
    ap.add_argument("--unfreeze-last", type=int, default=30, help="Fine-tune: number of final backbone layers to unfreeze (BatchNorm stays frozen).")
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--image-size", type=int, choices=VALID_SIZES, default=224)
    ap.add_argument("--lr", type=float, default=0.0, help="0 = 1e-3 (head) or 1e-5 (finetune).")
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-train-per-class", type=int, default=0, help="Pilot: cap training images per class (0 = all).")
    ap.add_argument("--max-val-per-class", type=int, default=0, help="Pilot: cap validation images per class (0 = all).")
    ap.add_argument("--run-name")
    ap.add_argument("--cpu-threads", type=int, default=0, help="Limit TensorFlow CPU threads (0 = TensorFlow default).")
    ap.add_argument("--sample-check", type=int, default=100, help="Images decoded by --validate-only.")
    ap.add_argument("--skip-decode-precheck", action="store_true")
    ap.add_argument("--drop-undecodable", action="store_true")
    ap.add_argument("--expected-classes", type=int, default=24)
    args = ap.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    TRAIN_REPORTS.mkdir(parents=True, exist_ok=True)
    df = load_manifest()
    names = class_names_from_manifest(df)
    if args.validate_only:
        return run_validate_only(df, names, args)
    errors, warnings, info = validate_manifest(df, args.expected_classes, check_paths=True)
    for w in warnings:
        log("WARNING: " + w)
    if errors:
        raise SystemExit("ERROR: manifest validation failed:\n  " + "\n  ".join(errors))
    if args.evaluate_only:
        return run_evaluate_only(df, names, args)
    return run_training(df, names, args)


if __name__ == "__main__":
    sys.exit(main())