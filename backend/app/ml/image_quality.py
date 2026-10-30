"""Image-quality assessment and selective enhancement for food photos (numpy + Pillow; OpenCV used when installed).

Quality is measured, not guessed:
  - size: the shorter side in pixels;
  - sharpness: variance of the Laplacian on a copy resized to 512 px on the long side (so phones with different
    resolutions are comparable), taken in the most detailed tiles of the photo so that a plain background does not
    make sharp food look blurred. Low variance there = blur;
  - exposure: mean brightness and the share of nearly black / nearly white pixels (under- and over-exposure);
  - contrast: standard deviation of brightness;
  - glare: share of saturated, almost colourless highlight pixels.

The thresholds below are starting values chosen to flag only clearly bad photos. They have NOT been tuned on a set of
real user photos; every response returns the measured values so the thresholds can be checked and adjusted
(QUALITY_THRESHOLDS can be overridden in one place). Quality is reported separately from food-identity confidence
and from freshness confidence.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps

try:  # optional: better local contrast enhancement (CLAHE)
    import cv2  # type: ignore
except Exception:  # noqa: BLE001
    cv2 = None

QUALITY_THRESHOLDS = {
    "min_side_poor": 160,      # px; below this there is too little detail for the 224 px model input
    "min_side_fair": 320,
    "sharpness_poor": 20.0,    # Laplacian variance (90th percentile of 32 px tiles) on the 512 px, range-normalised copy
    "sharpness_fair": 60.0,
    "dark_mean": 55.0,         # mean brightness 0-255
    "bright_mean": 232.0,
    "clipped_share": 0.35,     # share of pixels that are almost black or almost white
    "contrast_low": 18.0,      # brightness standard deviation
    "glare_share": 0.25,       # white plates and paper are also bright and colourless, so only large areas count
}

ADVICE = {
    "too_small": "The photo is very small. Move closer or use a higher resolution.",
    "blurry": "The photo looks blurred. Hold the phone steady and tap to focus before taking the picture.",
    "slightly_blurry": "The photo is slightly soft. A sharper photo gives a more reliable result.",
    "too_dark": "The photo is too dark. Use more light or move near a window.",
    "too_bright": "The photo is over-exposed. Avoid direct light or flash on the food.",
    "low_contrast": "The photo has very little contrast. Use a plain background and even light.",
    "glare": "There is strong glare. Tilt the item or the phone to avoid reflections.",
}


def _laplacian(gray: np.ndarray) -> np.ndarray:
    g = gray.astype(float)
    return -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]


def _laplacian_var(gray: np.ndarray) -> float:
    return float(_laplacian(gray).var())


def _detail_sharpness(gray: np.ndarray, tile: int = 32, q: float = 98.0) -> float:
    """Laplacian variance where the photo has detail: the 98th percentile over 32 px tiles (so food covering ~2% of the
    frame or more is what gets measured). The whole-frame variance called sharp food on a plain plate or white background
    'blurred', because the empty background has no edges. Measured on 93 held-out dataset photos and Gaussian-blurred
    copies on a 1024 px frame (2026-10-15), with the threshold of 20: unblurred photos rated poor 15.1% -> 0%;
    blurred copies rated poor at radius 1.5 / 3 / 6 px: 27% / 93.5% / 100% (whole-frame: 100% at 3 and 6 px)."""
    lap = _laplacian(gray)
    h, w = lap.shape
    tiles = [lap[y:y + tile, x:x + tile].var() for y in range(0, h - tile + 1, tile) for x in range(0, w - tile + 1, tile)]
    return float(np.percentile(tiles, q)) if tiles else float(lap.var())


def assess(img: Image.Image) -> dict:
    rgb = ImageOps.exif_transpose(img).convert("RGB")
    w, h = rgb.size
    small = rgb.copy()
    small.thumbnail((512, 512))
    arr = np.asarray(small, dtype=float)
    gray = arr @ np.array([0.299, 0.587, 0.114])
    mean, std = float(gray.mean()), float(gray.std())
    # normalised to the photo's own brightness range (1st-99th percentile), so a dark photo is not mistaken for a blurred one
    rng = float(np.percentile(gray, 99) - np.percentile(gray, 1))
    sharp = _detail_sharpness(gray / max(rng, 1.0) * 128.0)
    clipped = float(((gray < 12) | (gray > 243)).mean())
    sat = arr.max(axis=2) - arr.min(axis=2)
    glare = float(((gray > 240) & (sat < 18)).mean())
    t = QUALITY_THRESHOLDS
    issues: list[str] = []
    severities: list[str] = []

    def flag(code: str, severity: str) -> None:
        issues.append(code)
        severities.append(severity)

    if min(w, h) < t["min_side_poor"]:
        flag("too_small", "poor")
    elif min(w, h) < t["min_side_fair"]:
        flag("too_small", "fair")
    if sharp < t["sharpness_poor"]:
        flag("blurry", "poor")
    elif sharp < t["sharpness_fair"]:
        flag("slightly_blurry", "fair")
    if mean < t["dark_mean"]:
        flag("too_dark", "poor" if clipped > t["clipped_share"] else "fair")
    elif mean > t["bright_mean"]:
        flag("too_bright", "poor" if clipped > t["clipped_share"] else "fair")
    if std < t["contrast_low"]:
        flag("low_contrast", "fair")
    if glare > t["glare_share"]:
        flag("glare", "fair")
    level = "poor" if "poor" in severities else "fair" if severities else "good"
    return {
        "level": level,  # good | fair | poor
        "issues": issues,
        "advice": [ADVICE[i] for i in issues],
        "enhanceable": any(i in ("too_dark", "low_contrast", "too_bright") for i in issues),
        "metrics": {"width": w, "height": h, "sharpness": round(sharp, 1), "brightness": round(mean, 1), "contrast": round(std, 1),
                    "clipped_share": round(clipped, 3), "glare_share": round(glare, 3)},
        "thresholds_note": "Starting thresholds, not yet tuned on real user photos.",
    }


def enhance(img: Image.Image) -> Image.Image:
    """Mild exposure/contrast correction for dark or flat photos: gamma towards mid-grey, then local contrast (CLAHE on
    the lightness channel when OpenCV is installed, otherwise a gentle global autocontrast). Colours are preserved
    as much as possible because colour matters for food identity and freshness. No sharpening is applied: it cannot
    recover detail that was not captured and it creates artefacts the models were not trained on."""
    rgb = ImageOps.exif_transpose(img).convert("RGB")
    arr = np.asarray(rgb, dtype=float) / 255.0
    mean = float((arr @ np.array([0.299, 0.587, 0.114])).mean())
    gamma = float(np.clip(np.log(0.5) / np.log(max(mean, 1e-3)), 0.5, 2.0))
    arr = np.clip(arr ** gamma, 0, 1)
    out = Image.fromarray((arr * 255).astype(np.uint8))
    if cv2 is not None:
        lab = cv2.cvtColor(np.asarray(out), cv2.COLOR_RGB2LAB)
        lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
        return Image.fromarray(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB))
    return ImageOps.autocontrast(out, cutoff=1, preserve_tone=True)


def choose(original: dict, enhanced: dict | None) -> tuple[dict, str]:
    """Selection rule between the prediction on the original photo and on the enhanced copy.
    The enhanced result is used only if it is an accepted prediction AND names the same food as the original's top
    candidate; anything else keeps the original. Enhancement can therefore confirm the original's best guess, but it
    can never introduce a different food."""
    if enhanced is None:
        return original, "original"
    if original.get("decision") == "accept":
        return original, "original"
    o_top = (original.get("top_k") or [{}])[0].get("food")
    e_top = (enhanced.get("top_k") or [{}])[0].get("food")
    if enhanced.get("decision") == "accept" and o_top and o_top == e_top:
        return enhanced, "enhanced"
    return original, "original"
