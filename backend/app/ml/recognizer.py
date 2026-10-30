"""Food recognition service: 24-class MobileNetV2 + non-food rejection. TensorFlow is imported lazily, so the API can start
(and /health works) even when the model files are missing. Inference is kept separate from the HTTP routes."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.ml.freshness import FreshnessHead
from app.ml.imagenet_groups import CONTAINER, PRODUCT, group_of
from app.ml.rejection import Thresholds, decide_batch, min_mahalanobis, nearest_class

log = logging.getLogger("smartplate.recognizer")
BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = BACKEND_DIR / "models" / "production" / "food_classifier"

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP"}
MAX_PIXELS = 40_000_000
MIN_SIDE = 32
# ImageNet-1k classes 923 (plate) .. 957 (pomegranate) and 959 (carbonara) .. 965 (burrito); drinks, "hay" and "cup" excluded.
IMAGENET_FOOD_INDICES = list(range(923, 958)) + list(range(959, 966))
IMAGENET_SANITY = {933: "cheeseburger", 949: "strawberry", 954: "banana", 963: "pizza"}

MSG_NON_FOOD = "This image does not appear to contain a recognizable food item. Please upload a food image."
MSG_LOW_CONF = "I couldn't identify this food with enough confidence. Please upload a clearer photo of a single food item."
MSG_UNSUPPORTED = "This looks like food, but it is not one of the 24 foods SmartPlateAI can currently recognise."


class EmbedResult(tuple):
    """(probs, embeddings, food_mass) plus the ImageNet probabilities they were computed with."""

    def __new__(cls, values, imagenet):
        obj = super().__new__(cls, values)
        obj.imagenet = imagenet
        return obj


class ImageError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def decode_upload(data: bytes) -> Image.Image:
    """Validate and decode uploaded bytes into an RGB PIL image. Never trusts the filename or declared content type."""
    bad = ImageError("INVALID_IMAGE", "The file could not be read as an image. Please upload a valid JPG, PNG or WebP photo.", 400)
    try:
        probe = Image.open(io.BytesIO(data))
        fmt, (w, h) = probe.format, probe.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise bad from None
    if fmt not in ALLOWED_FORMATS:
        raise ImageError("UNSUPPORTED_MEDIA_TYPE", "This image format is not supported. Please upload a JPG, PNG or WebP photo.", 415)
    if w * h > MAX_PIXELS:
        raise ImageError("IMAGE_TOO_LARGE", "The image has too many pixels. Please upload a smaller photo.", 413)
    if min(w, h) < MIN_SIDE:
        raise ImageError("INVALID_IMAGE", "The image is too small to analyse. Please upload a larger photo.", 400)
    try:
        probe.verify()
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")  # phone photos: honour EXIF rotation; drop alpha like training did
        img.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise bad from None
    return img


class FoodRecognizer:
    def __init__(self, model_dir: str | Path | None = None, allow_uncalibrated: bool = False) -> None:
        self.model_dir = Path(model_dir or os.environ.get("FOOD_MODEL_DIR") or DEFAULT_MODEL_DIR)
        self.allow_uncalibrated = allow_uncalibrated or os.environ.get("ALLOW_UNCALIBRATED_REJECTION", "").lower() == "true"
        # Accept a prediction only when the softmax class and the nearest class in feature space agree (default on).
        self.require_agreement = os.environ.get("REJECTION_REQUIRE_AGREEMENT", "true").lower() != "false"
        self.status, self.status_message = "not_loaded", "Model not loaded yet."
        self.class_names: list[str] = []
        self.size = 224
        self.thresholds: Thresholds | None = None
        self.rejection_cfg: dict | None = None
        self._means = self._precision = None
        self._tf = self._multi = self._imagenet = None
        self._load_lock, self._infer_lock = threading.Lock(), threading.Lock()
        self.freshness = FreshnessHead(Path(os.environ.get("FRESHNESS_MODEL_DIR") or (BACKEND_DIR / "models" / "production" / "freshness")))

    # ------------------------------------------------------------------ loading
    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def load(self) -> bool:
        with self._load_lock:
            if self.ready:
                return True
            model_path, names_path = self.model_dir / "best.keras", self.model_dir / "class_names.json"
            if not (model_path.is_file() and names_path.is_file()):
                self.status, self.status_message = "model_missing", (
                    "The food recognition model is not installed. Train it, then copy the chosen run folder to models\\production\\food_classifier.")
                return False
            try:
                import tensorflow as tf  # noqa: PLC0415
                self._tf = tf
                meta = json.loads(names_path.read_text(encoding="utf-8"))
                self.class_names, self.size = list(meta["class_names"]), int(meta["input"]["shape"][0])
                model = tf.keras.models.load_model(str(model_path), compile=False)
                gap = next(layer for layer in model.layers if isinstance(layer, tf.keras.layers.GlobalAveragePooling2D))
                # model.input (the single "image" tensor), not model.inputs (a one-element list): the wrapper's expected
                # input structure must match how embed() calls it, with one batch tensor (avoids Keras 3's structure warning).
                self._multi = tf.keras.Model(model.input, [gap.output, model.output])
                if int(model.outputs[0].shape[-1]) != len(self.class_names):
                    raise ValueError("model output size does not match class_names.json")
                if not self._load_rejection(model_path):
                    return False
                try:  # optional: never blocks food recognition
                    self.freshness.load(sha256_file(model_path))
                except Exception:  # noqa: BLE001
                    log.exception("freshness head failed to load; freshness disabled")
                self._load_imagenet()
            except Exception:  # noqa: BLE001
                log.exception("food model failed to load")
                self.status, self.status_message = "error", "The food model failed to load. See the server log for details."
                return False
            self.status, self.status_message = "ready", "Food model ready."
            log.info("food model ready (%d classes, input %d, rejection calibrated=%s)", len(self.class_names), self.size, self.thresholds is not None)
            return True

    def _load_rejection(self, model_path: Path) -> bool:
        cfg_path, npz_path = self.model_dir / "rejection_config.json", self.model_dir / "rejection_stats.npz"
        if cfg_path.is_file() and npz_path.is_file():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            if cfg.get("model_sha256") != sha256_file(model_path):
                self.status, self.status_message = "error", "The rejection calibration does not match this model file. Re-run calibrate_rejection.py."
                return False
            stats = np.load(npz_path)
            self._means, self._precision = stats["means"], stats["precision"]
            self.thresholds, self.rejection_cfg = Thresholds(**cfg["thresholds"]), cfg
            return True
        if self.allow_uncalibrated:
            log.warning("non-food rejection is NOT calibrated; accepting every readable image (development mode)")
            return True
        self.status, self.status_message = "rejection_uncalibrated", (
            "Non-food rejection has not been calibrated for this model, so predictions are disabled. Run scripts\\calibrate_rejection.py.")
        return False

    def _load_imagenet(self) -> None:
        tf = self._tf
        self._imagenet = tf.keras.applications.MobileNetV2(weights="imagenet", include_top=True, input_shape=(224, 224, 3))
        decode = tf.keras.applications.mobilenet_v2.decode_predictions
        for idx, name in IMAGENET_SANITY.items():
            row = np.zeros((1, 1000), np.float32)
            row[0, idx] = 1.0
            if decode(row, top=1)[0][0][1] != name:
                raise ValueError(f"ImageNet class index {idx} is not '{name}'; the food-class index list is wrong")

    # ------------------------------------------------------------------ inference
    def prepare(self, img: Image.Image) -> np.ndarray:
        """Same resize as training: bilinear, antialiased, aspect ratio not preserved. Returns float32 0..255."""
        arr = np.asarray(img, dtype=np.uint8)
        return self._tf.image.resize(arr, [self.size, self.size], method="bilinear", antialias=True).numpy().astype(np.float32)

    def embed(self, x: np.ndarray):
        """x: (N, S, S, 3) float 0..255 -> (24-class probs, 1280-d embeddings, ImageNet food mass).
        The returned tuple also carries the ImageNet 1000-class probabilities as `.imagenet` (callers that unpack three
        values are unaffected)."""
        tf = self._tf
        with self._infer_lock:
            feats, probs = self._multi(x, training=False)
            x224 = x if x.shape[1] == 224 else tf.image.resize(x, [224, 224], method="bilinear", antialias=True).numpy()
            inet = self._imagenet(tf.keras.applications.mobilenet_v2.preprocess_input(np.array(x224, np.float32)), training=False)
        inet = inet.numpy()
        food_mass = inet[:, IMAGENET_FOOD_INDICES].sum(axis=1)
        return EmbedResult((probs.numpy(), feats.numpy(), food_mass), inet)

    def analyze_image(self, img: Image.Image) -> dict:
        out = self.embed(self.prepare(img)[None])
        probs, feats, fm = out
        inet = getattr(out, "imagenet", None)  # None for test doubles that return a plain tuple
        inet_top = int(np.argmax(inet[0])) if inet is not None else None
        inet_group = group_of(inet_top, IMAGENET_FOOD_INDICES) if inet is not None else "unknown"
        p = probs[0]
        top = np.argsort(-p)[:3]
        d = nearest = None
        decision_base = "accept"
        if self.thresholds is not None:
            d_arr, n_arr = nearest_class(feats, self._means, self._precision)
            d, nearest = float(d_arr[0]), int(n_arr[0])
            decision_base = str(decide_batch(probs, d_arr, fm, self.thresholds)[0])
            decision = str(decide_batch(probs, d_arr, fm, self.thresholds, nearest=n_arr if self.require_agreement else None)[0])
        else:
            decision = "accept"
        conf, margin = float(p[top[0]]), float(p[top[0]] - p[top[1]])
        reason = None
        if decision == "uncertain":
            th = self.thresholds
            if th is not None and (conf < th.conf_min or margin < th.margin_min):
                reason = "low_confidence"
            else:
                reason = "classifier_disagreement"
        elif decision in ("non_food", "unsupported_food"):
            reason = "far_from_supported_foods"
        accepted = decision == "accept"
        freshness = self.freshness.assess(feats[0], self.class_names[int(top[0])] if accepted else None, accepted)
        return {"decision": decision, "reason": reason, "calibrated": self.thresholds is not None, "confidence": conf, "margin": margin,
                "freshness": freshness,
                # internal: lets the API re-assess freshness for the food finally accepted or confirmed (never sent to clients)
                "features": feats[0],
                "top_k": [{"class_id": int(i), "food": self.class_names[int(i)], "score": round(float(p[i]), 4)} for i in top],
                # Package-like photo with no food evidence: ImageNet's top class is a generic container and the food signal is
                # below the calibrated floor. Not evidence of food; the API uses it to route to the label scanner, never to accept.
                "packaged_product": bool(inet_group == "container" and self.thresholds is not None
                                         and float(fm[0]) < self.thresholds.food_mass_low),
                "signals": {"feature_distance": d, "imagenet_food_mass": float(fm[0]),
                            "imagenet_top1": {"index": inet_top, "name": CONTAINER.get(inet_top) or PRODUCT.get(inet_top),
                                              "score": round(float(inet[0, inet_top]), 4)} if inet is not None else None,
                            "imagenet_group": inet_group,
                            "nearest_feature_class": self.class_names[nearest] if nearest is not None else None,
                            "decision_without_agreement_check": decision_base}}

    def assess_freshness(self, features, food: str | None) -> dict | None:
        """Freshness for a food whose identity is settled (accepted, verified by a second source, confirmed or corrected by
        the user), from the original photo's embedding. Explicit 'not_assessed' results when the head is not installed or
        was not trained for this food; None only when there is no embedding."""
        if features is None or not food:
            return None
        return self.freshness.assess(np.asarray(features), food, accepted=True)

    def info(self) -> dict:
        cfg = self.rejection_cfg or {}
        return {"status": self.status, "message": self.status_message, "n_classes": len(self.class_names), "input_size": self.size,
                "rejection_calibrated": self.thresholds is not None, "calibrated_with_non_food_examples": bool(cfg.get("calibrated_with_negatives")),
                "source_run": cfg.get("source_run"), "thresholds": cfg.get("thresholds"),
                "class_agreement_check": self.require_agreement, "freshness_model": self.freshness.status,
                "freshness_foods": self.freshness.cfg.get("supported_foods", []),
                "freshness_test_metrics": (self.freshness.cfg.get("test_metrics") or {}).get("overall")}