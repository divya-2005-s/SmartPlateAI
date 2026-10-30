"""Fresh / rotten condition classifier (the project's existing condition_classifier.keras), connected safely.

Before this module, the backend never loaded the trained condition classifier: freshness came only from an optional
logistic head that exists only after scripts/train_freshness_head.py has been run, and it was assessed only when the
food was accepted. The condition model is food-independent, so it can run on every food photo, separately from food
identity.

The model is used only after scripts/evaluate_condition_model.py has evaluated it and written condition_config.json
next to it. That file records, from evidence rather than assumption:
  - the class order (verified against labelled validation images, so a reversed fresh/rotten mapping is caught),
  - the input size and pixel preprocessing that the model actually expects,
  - decision thresholds calibrated on the validation split (never the test split),
  - test-split metrics and the SHA-256 of the model file the config belongs to.
Without a matching config the model is reported as "not_evaluated" and is not used.

Output: "fresh", "possibly_spoiled" (shown as Rotten), or "uncertain" (never forced into fresh or rotten).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

log = logging.getLogger("smartplate.condition")
BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DIR = BACKEND_DIR / "models" / "production" / "condition"
MODEL_NAMES = ("condition_classifier.keras", "best.keras", "model.keras")
FRESH_WORDS, ROTTEN_WORDS = {"fresh", "good", "healthy"}, {"rotten", "spoiled", "stale", "bad", "spoilt"}

MESSAGES = {
    "fresh": "Looks fresh in this photo. This is a visual estimate only; it cannot detect microbes, toxins or residues.",
    "possibly_spoiled": "Visible signs suggest this may be rotten or spoiled. Inspect it carefully and discard it if in doubt.",
    "uncertain": "Freshness could not be judged reliably from this photo.",
    "not_assessed": "Freshness was not assessed.",
}


def preprocess_array(img: Image.Image, size: int, mode: str) -> np.ndarray:
    rgb = ImageOps.exif_transpose(img).convert("RGB").resize((size, size), Image.BILINEAR)
    x = np.asarray(rgb, dtype=np.float32)
    if mode == "scale_0_1":
        x = x / 255.0
    elif mode == "minus1_1":
        x = x / 127.5 - 1.0
    elif mode != "raw_0_255":
        raise ValueError(f"unknown preprocessing mode {mode}")
    return x


def class_role(name: str) -> str:
    n = name.strip().casefold()
    if n in FRESH_WORDS or n.startswith("fresh"):
        return "fresh"
    if n in ROTTEN_WORDS or n.startswith("rotten") or n.startswith("spoil"):
        return "rotten"
    return "unknown"


def decide(probs: np.ndarray, classes: list[str], t_fresh: float, t_rotten: float) -> tuple[str, float | None]:
    """probs: class probabilities in model order. 'Unknown'-type classes count against both decisions."""
    roles = [class_role(c) for c in classes]
    p_fresh = float(sum(p for p, r in zip(probs, roles) if r == "fresh"))
    p_rotten = float(sum(p for p, r in zip(probs, roles) if r == "rotten"))
    if p_rotten >= t_rotten and p_rotten > p_fresh:
        return "possibly_spoiled", round(p_rotten, 3)
    if p_fresh >= t_fresh and p_fresh > p_rotten:
        return "fresh", round(p_fresh, 3)
    return "uncertain", None


class ConditionModel:
    def __init__(self, model_dir: str | Path | None = None) -> None:
        self.dir = Path(model_dir or os.environ.get("CONDITION_MODEL_DIR") or DEFAULT_DIR)
        self._lock = threading.Lock()
        self._model = None
        self.cfg: dict = {}
        self.status = "not_loaded"
        self.message = ""

    def _model_path(self) -> Path | None:
        if self.cfg.get("model_file"):
            p = Path(self.cfg["model_file"])
            return p if p.is_absolute() else self.dir / p
        return next((self.dir / n for n in MODEL_NAMES if (self.dir / n).is_file()), None)

    def load(self) -> bool:
        with self._lock:
            if self._model is not None:
                return True
            if self.status in ("not_installed", "not_evaluated", "model_mismatch", "error"):
                return False
            cfg_path = self.dir / "condition_config.json"
            if not cfg_path.is_file():
                self.status = "not_evaluated" if self._model_path() else "not_installed"
                self.message = ("The condition model has not been evaluated yet. Run scripts/evaluate_condition_model.py "
                                "with --install." if self.status == "not_evaluated" else "No condition model is installed.")
                return False
            self.cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            path = self._model_path()
            if path is None or not path.is_file():
                self.status, self.message = "not_installed", "The condition model file named in condition_config.json is missing."
                return False
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != self.cfg.get("model_sha256"):
                self.status = "model_mismatch"
                self.message = "condition_config.json was written for a different model file. Re-run the evaluation."
                log.warning(self.message)
                return False
            try:
                import tensorflow as tf  # noqa: PLC0415  (lazy: the API starts without TensorFlow)
                self._model = tf.keras.models.load_model(path, compile=False)
            except Exception:  # noqa: BLE001
                log.exception("condition model failed to load")
                self.status, self.message = "error", "The condition model could not be loaded."
                return False
            self.status = "ready"
            return True

    def predict_probs(self, img: Image.Image) -> np.ndarray:
        x = preprocess_array(img, int(self.cfg["input_size"]), self.cfg["preprocessing"])[None]
        out = np.asarray(self._model(x, training=False))[0]
        if out.ndim == 0 or out.shape == (1,):  # single sigmoid output: probability of class index 1
            p1 = float(np.ravel(out)[0])
            return np.array([1.0 - p1, p1])
        if not np.isclose(out.sum(), 1.0, atol=1e-3) or (out < 0).any():  # logits -> softmax
            e = np.exp(out - out.max())
            out = e / e.sum()
        return out

    def assess(self, img: Image.Image, image_quality: dict | None = None, is_food: bool = True) -> dict:
        base = {"status": "not_assessed", "confidence": None, "model": "condition_classifier", "model_status": self.status}
        if not is_food:
            return {**base, "message": "Freshness is not assessed when the photo does not show food."}
        if image_quality and image_quality.get("level") == "poor":
            return {**base, "message": "Freshness was not assessed because the photo quality is too low. " +
                    " ".join(image_quality.get("advice", [])[:1])}
        if not self.load():
            return {**base, "model_status": self.status, "message": self.message or MESSAGES["not_assessed"]}
        probs = self.predict_probs(img)
        classes = self.cfg["class_names"]
        status, conf = decide(probs, classes, self.cfg["t_fresh"], self.cfg["t_rotten"])
        return {"status": status, "confidence": conf, "model": "condition_classifier", "model_status": "ready",
                "message": MESSAGES[status],
                "probabilities": {c: round(float(p), 4) for c, p in zip(classes, probs)},
                "evidence": (f"Model probabilities: " + ", ".join(f"{c} {p:.2f}" for c, p in zip(classes, probs)) +
                             f". Thresholds calibrated on validation images: fresh >= {self.cfg['t_fresh']:.2f}, "
                             f"rotten >= {self.cfg['t_rotten']:.2f}."),
                "limitation": "A photo cannot establish food safety; it shows only visible signs of spoilage."}

    def info(self) -> dict:
        self.load()
        return {"status": self.status, "message": self.message, "classes": self.cfg.get("class_names"),
                "preprocessing": self.cfg.get("preprocessing"), "test_metrics": self.cfg.get("test_metrics")}
