"""Non-food / low-confidence rejection logic. Pure numpy (no TensorFlow), so it is unit-testable.

Three independent signals are combined:
  1. feature distance: Mahalanobis distance of the image embedding to the nearest of the 24 food classes
  2. ImageNet food mass: probability mass an ORIGINAL ImageNet MobileNetV2 puts on food-related ImageNet classes
  3. the 24-class softmax confidence and top1-top2 margin
Softmax confidence alone is never used to decide "this is food".
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Thresholds:
    food_mass_low: float   # ImageNet food mass below this = "does not look like food" evidence
    maha_high: float       # feature distance above this = "far from all 24 foods" evidence
    conf_min: float        # minimum top-1 softmax score to name a food
    margin_min: float      # minimum gap between top-1 and top-2 scores


def fit_feature_stats(feats: np.ndarray, labels: np.ndarray, num_classes: int, shrinkage: float = 0.05):
    """Class means + one shared (shrinkage-regularised) precision matrix."""
    feats = np.asarray(feats, np.float64)
    labels = np.asarray(labels)
    if (np.bincount(labels, minlength=num_classes) == 0).any():
        raise ValueError("every class needs at least one training embedding")
    d = feats.shape[1]
    means = np.stack([feats[labels == c].mean(axis=0) for c in range(num_classes)])
    centered = feats - means[labels]
    cov = centered.T @ centered / max(len(feats) - 1, 1)
    cov = (1.0 - shrinkage) * cov + shrinkage * (np.trace(cov) / d) * np.eye(d)
    return means.astype(np.float32), np.linalg.inv(cov).astype(np.float32)


def mahalanobis_all(feats: np.ndarray, means: np.ndarray, precision: np.ndarray) -> np.ndarray:
    """Squared Mahalanobis distance of every embedding to every class mean, shape (N, K)."""
    f = np.asarray(feats, np.float64)
    m = np.asarray(means, np.float64)
    p = np.asarray(precision, np.float64)
    fp = f @ p
    d = np.einsum("nd,nd->n", fp, f)[:, None] - 2.0 * (fp @ m.T) + np.einsum("kd,kd->k", m @ p, m)[None, :]
    return np.maximum(d, 0.0)


def min_mahalanobis(feats: np.ndarray, means: np.ndarray, precision: np.ndarray) -> np.ndarray:
    return mahalanobis_all(feats, means, precision).min(axis=1)


def nearest_class(feats: np.ndarray, means: np.ndarray, precision: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(distance to the nearest class mean, index of that class) for each embedding."""
    d = mahalanobis_all(feats, means, precision)
    return d.min(axis=1), d.argmin(axis=1)


def decide_batch(probs: np.ndarray, d_min: np.ndarray, food_mass: np.ndarray, th: Thresholds,
                 nearest: np.ndarray | None = None) -> np.ndarray:
    """If `nearest` (index of the nearest class mean in feature space) is given, a prediction is only accepted when the
    softmax top-1 class and the nearest-feature class agree; otherwise it is downgraded to "uncertain". This is a
    consistency check between two views of the same embedding and adds no new threshold."""
    probs = np.asarray(probs)
    srt = np.sort(probs, axis=1)
    conf, margin = srt[:, -1], srt[:, -1] - srt[:, -2]
    out = np.full(len(probs), "accept", dtype=object)
    far = np.asarray(d_min) > th.maha_high
    non_food = far & (np.asarray(food_mass) < th.food_mass_low)
    out[~far & ((conf < th.conf_min) | (margin < th.margin_min))] = "uncertain"
    if nearest is not None:
        out[~far & (np.asarray(nearest) != probs.argmax(axis=1))] = "uncertain"
    out[far & ~non_food] = "unsupported_food"   # looks food-like to ImageNet but far from the 24 supported foods
    out[non_food] = "non_food"                  # both independent signals say "not food"
    return out


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (float(max(0.0, centre - half)), float(min(1.0, centre + half)))


def choose_gate_thresholds(pos_fm, pos_md, neg_fm=None, neg_md=None, max_false_reject: float = 0.02) -> dict:
    """Pick (food_mass_low, maha_high) from the calibration half only.
    Without negatives: conservative percentiles of the valid-food data (P2 of food mass, P99 of distance).
    With negatives: maximise non-food rejection subject to falsely rejecting at most `max_false_reject` of valid foods."""
    pos_fm, pos_md = np.asarray(pos_fm), np.asarray(pos_md)
    t_md_grid = np.quantile(pos_md, [0.90, 0.95, 0.97, 0.98, 0.99, 0.995, 0.999])
    t_fm_grid = np.quantile(pos_fm, [0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.50])
    have_neg = neg_fm is not None and len(neg_fm) >= 30
    best = None
    for t_md in t_md_grid:
        for t_fm in t_fm_grid:
            false = float(np.mean((pos_fm < t_fm) & (pos_md > t_md)))
            if false > max_false_reject:
                continue
            rej = float(np.mean((np.asarray(neg_fm) < t_fm) & (np.asarray(neg_md) > t_md))) if have_neg else 0.0
            key = (rej, -false)
            if best is None or key > best[0]:
                best = (key, float(t_fm), float(t_md), false, rej)
    if not have_neg or best is None:
        t_md, t_fm = float(np.quantile(pos_md, 0.99)), float(np.quantile(pos_fm, 0.02))
        return {"food_mass_low": t_fm, "maha_high": t_md, "method": "positive-only percentiles (P2 food mass, P99 distance)",
                "false_reject_calib": float(np.mean((pos_fm < t_fm) & (pos_md > t_md))), "neg_reject_calib": None}
    return {"food_mass_low": best[1], "maha_high": best[2], "method": f"grid search on calibration negatives (false-reject <= {max_false_reject:.0%})",
            "false_reject_calib": best[3], "neg_reject_calib": best[4]}


def choose_conf_margin(conf, margin, correct, target_acc: float = 0.95, min_accepted: int = 50) -> dict:
    """Risk-coverage calibration on validation predictions: keep the most predictions whose accuracy still meets the target."""
    conf, margin, correct = np.asarray(conf), np.asarray(margin), np.asarray(correct, bool)
    best, fallback = None, None
    for tc in np.concatenate([[0.0], np.quantile(conf, np.arange(0.02, 0.92, 0.02))]):
        for tm in np.concatenate([[0.0], np.quantile(margin, np.arange(0.05, 0.60, 0.05))]):
            acc_mask = (conf >= tc) & (margin >= tm)
            n = int(acc_mask.sum())
            if n < min_accepted:
                continue
            acc, cov = float(correct[acc_mask].mean()), n / len(conf)
            if acc >= target_acc and (best is None or (cov, acc) > (best[2], best[1])):
                best = (float(tc), acc, cov, float(tm))
            if fallback is None or acc > fallback[1]:
                fallback = (float(tc), acc, cov, float(tm))
    chosen, met = (best, True) if best else (fallback, False)
    if chosen is None:
        return {"conf_min": 0.0, "margin_min": 0.0, "accuracy_of_accepted": None, "coverage": None, "target_met": False}
    return {"conf_min": chosen[0], "margin_min": chosen[3], "accuracy_of_accepted": chosen[1], "coverage": chosen[2], "target_met": met}