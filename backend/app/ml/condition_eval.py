"""Pure evaluation helpers for the condition (fresh / rotten) classifier. No TensorFlow here, so they are unit-tested.

Used by scripts/evaluate_condition_model.py. Nothing in here touches the test split except `metrics`, which is
called once on the test split after every choice (preprocessing, class order, thresholds) was made on validation.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from app.ml.condition import class_role

PATH_COLS = ["image_path", "filepath", "file_path", "path", "image", "img_path", "file", "filename"]
COND_COLS = ["condition", "condition_label", "freshness", "quality", "state", "label_condition", "fresh_rotten"]
SPLIT_COLS = ["split", "subset", "set", "partition"]
FOOD_COLS = ["food", "food_label", "label", "class"]


def detect_columns(columns: list[str]) -> dict:
    low = {c.strip().casefold(): c for c in columns}
    pick = lambda opts: next((low[o] for o in opts if o in low), None)  # noqa: E731
    return {"path": pick(PATH_COLS), "condition": pick(COND_COLS), "split": pick(SPLIT_COLS), "food": pick(FOOD_COLS)}


def split_role(value) -> str:
    v = str(value).strip().casefold()
    if v in ("val", "valid", "validation", "dev"):
        return "validation"
    if v in ("test", "testing", "holdout"):
        return "test"
    if v in ("train", "training"):
        return "train"
    return "other"


def read_class_names(path: str | Path) -> list[str]:
    """Accepts {"class_names": [...]}, {"classes": [...]}, {"labels": [...]}, {"0": "fresh", ...} or a plain list."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [str(x) for x in data]
    for k in ("class_names", "classes", "labels", "condition_classes"):
        if isinstance(data.get(k), list):
            return [str(x) for x in data[k]]
    for k in ("index_to_class", "idx_to_class", "class_index"):
        if isinstance(data.get(k), dict):
            m = data[k]
            return [str(m[i]) for i in sorted(m, key=lambda x: int(x))]
    if data and all(str(k).isdigit() for k in data):
        return [str(data[k]) for k in sorted(data, key=lambda x: int(x))]
    if isinstance(data.get("class_to_index"), dict):
        inv = {int(v): k for k, v in data["class_to_index"].items()}
        return [inv[i] for i in sorted(inv)]
    raise ValueError("No class list found in the metadata JSON.")


def role_probs(probs: np.ndarray, classes: list[str]) -> tuple[np.ndarray, np.ndarray]:
    roles = [class_role(c) for c in classes]
    pf = probs[:, [i for i, r in enumerate(roles) if r == "fresh"]].sum(axis=1)
    pr = probs[:, [i for i, r in enumerate(roles) if r == "rotten"]].sum(axis=1)
    return pf, pr


def argmax_roles(probs: np.ndarray, classes: list[str]) -> np.ndarray:
    roles = np.array([class_role(c) for c in classes])
    return roles[probs.argmax(axis=1)]


def mapping_check(probs: np.ndarray, classes: list[str], y: np.ndarray) -> dict:
    """Compare accuracy with the stated class order and with fresh/rotten swapped (validation data only)."""
    y = np.asarray(y)
    mask = np.isin(y, ["fresh", "rotten"])
    pred = argmax_roles(probs[mask], classes)
    swapped = np.where(pred == "fresh", "rotten", np.where(pred == "rotten", "fresh", pred))
    acc = float((pred == y[mask]).mean()) if mask.any() else float("nan")
    acc_sw = float((swapped == y[mask]).mean()) if mask.any() else float("nan")
    return {"accuracy_as_stated": round(acc, 4), "accuracy_if_swapped": round(acc_sw, 4),
            "likely_reversed": bool(mask.any() and acc_sw > acc + 0.2), "n": int(mask.sum())}


def choose_thresholds(pf: np.ndarray, pr: np.ndarray, y: np.ndarray, target_precision: float = 0.9, min_n: int = 20) -> dict:
    """Lowest thresholds whose fresh / rotten calls reach the target precision on validation. Images below both
    thresholds are 'uncertain', so the model is never forced to choose."""
    y = np.asarray(y)

    def lowest(p: np.ndarray, want: str) -> float:
        for t in np.round(np.arange(0.5, 0.995, 0.01), 2):
            m = p >= t
            if m.sum() >= min_n and (y[m] == want).mean() >= target_precision:
                return float(t)
        return 0.99

    return {"t_fresh": lowest(pf, "fresh"), "t_rotten": lowest(pr, "rotten"), "target_precision": target_precision}


def decide_all(pf: np.ndarray, pr: np.ndarray, t_fresh: float, t_rotten: float) -> np.ndarray:
    out = np.full(len(pf), "uncertain", dtype=object)
    out[(pf >= t_fresh) & (pf > pr)] = "fresh"
    out[(pr >= t_rotten) & (pr > pf)] = "rotten"
    return out


def metrics(y_true, y_pred, labels=("fresh", "rotten", "uncertain")) -> dict:
    y_true, y_pred = np.asarray(y_true, dtype=object), np.asarray(y_pred, dtype=object)
    cm = {t: {p: int(((y_true == t) & (y_pred == p)).sum()) for p in labels} for t in labels if (y_true == t).any()}
    per = {}
    for c in ("fresh", "rotten"):
        tp = int(((y_true == c) & (y_pred == c)).sum())
        fp = int(((y_true != c) & (y_pred == c)).sum())
        fn = int(((y_true == c) & (y_pred != c)).sum())
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        per[c] = {"precision": round(prec, 4), "recall": round(rec, 4),
                  "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0, "support": int((y_true == c).sum())}
    decided = y_pred != "uncertain"
    known = np.isin(y_true, ["fresh", "rotten"])
    return {"confusion_matrix": cm, "per_class": per, "macro_f1": round(float(np.mean([per[c]["f1"] for c in per])), 4),
            "coverage": round(float(decided[known].mean()), 4) if known.any() else None,
            "accuracy_on_decided": round(float((y_pred[decided & known] == y_true[decided & known]).mean()), 4)
            if (decided & known).any() else None}


def ahash(img: Image.Image) -> int:
    g = np.asarray(img.convert("L").resize((8, 8), Image.BILINEAR), dtype=float)
    bits = (g > g.mean()).ravel()
    return int("".join("1" if b else "0" for b in bits), 2)


def cross_split_duplicates(hashes: dict[str, list[int]], max_distance: int = 0) -> dict:
    """Count images whose 8x8 average hash also appears in another split (exact or within max_distance bits)."""
    out = {}
    names = list(hashes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            sb = set(hashes[b])
            if max_distance == 0:
                n = sum(1 for h in hashes[a] if h in sb)
            else:
                arr_b = np.array(list(sb), dtype=np.uint64)
                n = 0
                for h in hashes[a]:
                    x = np.bitwise_xor(arr_b, np.uint64(h))
                    if (np.array([bin(int(v)).count("1") for v in x]) <= max_distance).any():
                        n += 1
            out[f"{a}~{b}"] = n
    return out
