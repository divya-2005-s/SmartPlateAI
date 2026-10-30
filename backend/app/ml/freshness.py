"""Fresh / possibly spoiled / uncertain, from the food model's own 1280-d embedding (pure numpy at inference).

A small logistic-regression head is trained by scripts/train_freshness_head.py on images that have trusted
Fresh/Rotten labels, and its two thresholds are calibrated on the validation split. It is applied only to foods it
was trained on, and only when the food itself was accepted by the recogniser. Identity confidence and freshness
confidence are reported separately. A photo cannot establish microbiological safety.
Files (models/production/freshness/): freshness_head.npz, freshness_config.json
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("smartplate.freshness")
NOT_ASSESSED = "not_assessed"


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -40, 40)))


def fit_logistic(x: np.ndarray, y: np.ndarray, l2: float = 1e-2, epochs: int = 400, lr: float = 0.5) -> dict:
    """Class-balanced L2 logistic regression with full-batch gradient descent on standardised features."""
    x = np.asarray(x, np.float64)
    y = np.asarray(y, np.float64)
    mean, scale = x.mean(0), x.std(0) + 1e-6
    z = (x - mean) / scale
    pos = max(1.0, y.sum())
    neg = max(1.0, len(y) - y.sum())
    sw = np.where(y == 1, len(y) / (2 * pos), len(y) / (2 * neg))
    w, b = np.zeros(z.shape[1]), 0.0
    for _ in range(epochs):
        p = sigmoid(z @ w + b)
        g = (p - y) * sw
        w -= lr * (z.T @ g / len(y) + l2 * w)
        b -= lr * g.mean()
    return {"mean": mean, "scale": scale, "w": w, "b": np.array(b)}


def predict_proba(head: dict, x: np.ndarray) -> np.ndarray:
    z = (np.asarray(x, np.float64) - head["mean"]) / head["scale"]
    return sigmoid(z @ head["w"] + float(head["b"]))


def choose_thresholds(p_spoiled: np.ndarray, y: np.ndarray, target_precision: float = 0.9, min_n: int = 20) -> dict:
    """t_spoiled: lowest threshold whose 'possibly spoiled' calls reach the target precision;
    t_fresh: highest threshold whose 'fresh' calls reach the target precision. Between them -> uncertain."""
    p, y = np.asarray(p_spoiled), np.asarray(y).astype(bool)
    grid = np.unique(np.round(np.quantile(p, np.linspace(0, 1, 201)), 6))
    t_sp, t_fr = 1.01, -0.01
    for t in grid:
        m = p >= t
        if m.sum() >= min_n and y[m].mean() >= target_precision:
            t_sp = float(t)
            break
    for t in grid[::-1]:
        m = p <= t
        if m.sum() >= min_n and (~y[m]).mean() >= target_precision:
            t_fr = float(t)
            break
    if t_fr >= t_sp:  # overlapping -> keep a gap so that borderline images are "uncertain"
        mid = (t_fr + t_sp) / 2
        t_fr, t_sp = mid - 1e-6, mid + 1e-6
    sp, fr = p >= t_sp, p <= t_fr
    unc = ~(sp | fr)
    return {"t_spoiled": t_sp, "t_fresh": t_fr, "target_precision": target_precision,
            "precision_spoiled": float(y[sp].mean()) if sp.any() else None, "precision_fresh": float((~y[fr]).mean()) if fr.any() else None,
            "coverage": float(1 - unc.mean()), "n": int(len(p))}


def decide(p: float, t_fresh: float, t_spoiled: float) -> str:
    if p >= t_spoiled:
        return "possibly_spoiled"
    if p <= t_fresh:
        return "fresh"
    return "uncertain"


MESSAGES = {
    "fresh": "Looks fresh in this photo (visual estimate only; it cannot show microbes or residues).",
    "possibly_spoiled": "Visible signs suggest this may be spoiled. Inspect it carefully and discard it if in doubt.",
    "uncertain": "Freshness could not be judged reliably from this photo.",
    NOT_ASSESSED: "Freshness was not assessed.",
}

# Display label per status. "uncertain" is the band between the two calibrated thresholds: the model was trained on
# Fresh/Rotten labels only, so it is NOT a measured "partially deteriorated" class; it is shown as borderline.
CONDITION_LABELS = {
    "fresh": ("Fresh", "No visible signs of spoilage were detected in this photo."),
    "uncertain": ("Borderline / unclear", "The photo shows neither clearly fresh nor clearly spoiled features. It may be starting to "
                                          "deteriorate, so inspect it before eating."),
    "possibly_spoiled": ("Rotten / possibly spoiled", "Visible signs of spoilage were detected in this photo."),
    NOT_ASSESSED: ("Not assessed", None),
}
PERCENT_NOTE = ("No freshness or deterioration percentage is shown. The freshness model was trained only on images labelled "
                "fresh or rotten, so it cannot measure how much of the food has deteriorated, and its confidence in a label is "
                "not a freshness percentage.")


def annotate(freshness: dict | None) -> dict | None:
    """Adds the display label and states explicitly that no freshness/deterioration percentage is available."""
    if not freshness:
        return freshness
    label, summary = CONDITION_LABELS.get(freshness.get("status"), CONDITION_LABELS[NOT_ASSESSED])
    return {**freshness, "condition_label": label, "condition_summary": summary, "freshness_percent": None,
            "deterioration_percent": None, "percent_supported": False, "percent_note": PERCENT_NOTE}


UNAVAILABLE = {
    "not_installed": "Freshness detection is not installed on this server (no trained freshness model), so the condition "
                     "of this food was not assessed.",
    "model_mismatch": "The installed freshness model was trained on a different food-recognition model, so it is disabled "
                      "and the condition of this food was not assessed.",
    "error": "The freshness model could not be loaded, so the condition of this food was not assessed.",
}


class FreshnessHead:
    def __init__(self, model_dir: Path) -> None:
        self.dir = model_dir
        self.head: dict | None = None
        self.cfg: dict = {}
        self.status = "not_installed"

    def load(self, food_model_sha256: str) -> bool:
        npz, cfgp = self.dir / "freshness_head.npz", self.dir / "freshness_config.json"
        if not (npz.is_file() and cfgp.is_file()):
            self.status = "not_installed"
            return False
        cfg = json.loads(cfgp.read_text(encoding="utf-8"))
        if cfg.get("food_model_sha256") != food_model_sha256:
            self.status = "model_mismatch"
            log.warning("freshness head was trained on a different food model; disabled")
            return False
        try:
            d = np.load(npz)
            head = {k: d[k] for k in ("mean", "scale", "w", "b")}
        except Exception:  # noqa: BLE001  (corrupt or incomplete file: report it, never guess)
            log.exception("freshness head could not be loaded; freshness disabled")
            self.status = "error"
            return False
        self.head, self.cfg, self.status = head, cfg, "ready"
        return True

    def assess(self, feats: np.ndarray, food: str | None, accepted: bool) -> dict:
        base = {"status": NOT_ASSESSED, "confidence": None, "p_spoiled": None, "model_status": self.status}
        if self.head is None:
            return {**base, "message": UNAVAILABLE.get(self.status, UNAVAILABLE["not_installed"])}
        if not accepted or food is None:
            return {**base, "message": "Freshness is only assessed when the food is identified confidently."}
        supported = {f.casefold(): f for f in self.cfg.get("supported_foods", [])}
        if food.strip().casefold() not in supported:
            return {**base, "supported_food": False,
                    "message": f"Freshness assessment is not supported for {food}: the freshness model was trained only for "
                               + ", ".join(self.cfg.get("supported_foods", [])) + "."}
        food = supported[food.strip().casefold()]
        p = float(predict_proba(self.head, feats.reshape(1, -1))[0])
        st = decide(p, self.cfg["t_fresh"], self.cfg["t_spoiled"])
        conf = None if st == "uncertain" else round(p if st == "possibly_spoiled" else 1 - p, 3)
        return {"status": st, "confidence": conf, "p_spoiled": round(p, 4), "model_status": "ready", "message": MESSAGES[st],
                "evidence": f"Model score for visible spoilage: {p:.2f} (thresholds: fresh <= {self.cfg['t_fresh']:.2f}, "
                            f"possibly spoiled >= {self.cfg['t_spoiled']:.2f}, calibrated on validation images).",
                "limitation": "A photo cannot establish microbiological safety or detect toxins."}
