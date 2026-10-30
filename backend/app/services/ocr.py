"""Tesseract OCR through its command-line program (no extra Python package needed).

Set TESSERACT_CMD in backend/.env if tesseract.exe is not on PATH, e.g.
TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:  # optional OpenCV: CLAHE, adaptive threshold and perspective correction
    import cv2  # type: ignore
except Exception:  # noqa: BLE001
    cv2 = None

from app.core.config import get_settings

WINDOWS_DEFAULTS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]
TIMEOUT_S = 40


class OCRUnavailable(Exception):
    pass


def tesseract_cmd() -> str | None:
    configured = get_settings().tesseract_cmd or os.environ.get("TESSERACT_CMD")
    if configured:
        return configured if Path(configured).is_file() or shutil.which(configured) else None
    found = shutil.which("tesseract")
    if found:
        return found
    return next((p for p in WINDOWS_DEFAULTS if Path(p).is_file()), None)


def preprocess(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img)
    longest = max(g.size)
    if longest < 1400:  # small photos: upscale so label text is large enough for Tesseract
        f = 1400 / longest
        g = g.resize((int(g.width * f), int(g.height * f)), Image.LANCZOS)
    elif longest > 3200:
        f = 3200 / longest
        g = g.resize((int(g.width * f), int(g.height * f)), Image.LANCZOS)
    return ImageOps.autocontrast(g, cutoff=1)


def _run(img: Image.Image, psm: int = 3) -> dict:
    cmd = tesseract_cmd()
    if not cmd:
        raise OCRUnavailable("Tesseract OCR is not installed or TESSERACT_CMD is not set.")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    try:
        proc = subprocess.run([cmd, "stdin", "stdout", "--psm", str(psm), "-l", "eng", "tsv"], input=buf.getvalue(),
                              capture_output=True, timeout=TIMEOUT_S, check=False)
    except FileNotFoundError as exc:
        raise OCRUnavailable("Tesseract OCR could not be started.") from exc
    except subprocess.TimeoutExpired as exc:
        raise OCRUnavailable("Tesseract OCR timed out.") from exc
    if proc.returncode != 0:
        raise OCRUnavailable("Tesseract OCR failed: " + proc.stderr.decode("utf-8", "ignore")[:200])
    lines: dict[tuple, list[str]] = {}
    confs: list[float] = []
    words: list[dict] = []
    for row in proc.stdout.decode("utf-8", "ignore").splitlines()[1:]:
        parts = row.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        word, conf = parts[11].strip(), float(parts[10])
        if not word or conf < 0:
            continue
        lines.setdefault((int(parts[2]), int(parts[3]), int(parts[4])), []).append(word)
        confs.append(conf)
        words.append({"text": word, "conf": conf, "height": int(parts[9]), "top": int(parts[7]), "left": int(parts[6])})
    text = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
    return {"text": text, "confidence": round(sum(confs) / len(confs), 1) if confs else 0.0, "word_count": len(confs),
            "score": sum(1 for c in confs if c >= 60), "words": words}


def _order_quad(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def perspective_correct(img: Image.Image) -> Image.Image | None:
    """If the photo shows a clear rectangular label (a 4-corner outline covering at least 25% of the image),
    warp it to a flat, front-on rectangle. Returns None when no such outline exists (e.g. crumpled pouches)."""
    if cv2 is None:
        return None
    rgb = np.asarray(ImageOps.exif_transpose(img).convert("RGB"))
    f = 1000 / max(rgb.shape[:2]) if max(rgb.shape[:2]) > 1000 else 1.0
    small = cv2.resize(rgb, None, fx=f, fy=f) if f != 1.0 else rgb
    edges = cv2.Canny(cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 0), 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_min = 0.25 * small.shape[0] * small.shape[1]
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) == 4 and cv2.contourArea(approx) >= area_min and cv2.isContourConvex(approx):
            q = _order_quad(approx.reshape(4, 2).astype(np.float32) / f)
            w = int(max(np.linalg.norm(q[0] - q[1]), np.linalg.norm(q[3] - q[2])))
            h = int(max(np.linalg.norm(q[0] - q[3]), np.linalg.norm(q[1] - q[2])))
            if w < 100 or h < 100:
                return None
            m = cv2.getPerspectiveTransform(q, np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32))
            return Image.fromarray(cv2.warpPerspective(rgb, m, (w, h)))
    return None


def label_variants(img: Image.Image, rotation: int = 0) -> list[tuple[str, Image.Image]]:
    """Extra versions of a back label for a second OCR attempt: local contrast (CLAHE), adaptive threshold (uneven
    light and glare), and a perspective-corrected crop when a rectangular label outline is visible."""
    out = []
    base = np.asarray(preprocess(img))
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(base)
    out.append(("clahe", Image.fromarray(clahe)))
    den = cv2.fastNlMeansDenoising(clahe, None, 7, 7, 21) if max(base.shape) <= 2400 else clahe
    out.append(("adaptive_threshold", Image.fromarray(cv2.adaptiveThreshold(den, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                                           cv2.THRESH_BINARY, 31, 15))))
    flat = perspective_correct(img)
    if flat is not None:
        out.append(("perspective", preprocess(flat)))
    return [(n, v.rotate(rotation, expand=True) if rotation else v) for n, v in out]


def ocr_image(img: Image.Image) -> dict:
    """OCR with an orientation fallback: if the upright read is poor, try 90/180/270 degrees and keep the best."""
    base = preprocess(img)
    best = dict(_run(base), rotation=0)
    if best["word_count"] < 12 or best["confidence"] < 55:
        for angle in (90, 270, 180):
            r = dict(_run(base.rotate(angle, expand=True)), rotation=angle)
            if r["score"] > best["score"]:
                best = r
    if (best["word_count"] < 15 or best["confidence"] < 70) and cv2 is not None:
        # Poor read: retry on label-specific variants and keep the best (more confident words wins).
        for name, variant in label_variants(img, best["rotation"]):
            r = dict(_run(variant), rotation=best["rotation"], variant=name)
            if r["score"] > best["score"]:
                best = r
    conf, words = best["confidence"], best["word_count"]
    best["quality"] = "good" if words >= 15 and conf >= 70 else "low" if words >= 4 else "unreadable"
    best.pop("score", None)
    best.pop("words", None)
    return best


# ------------------------------------------------------------------ front of pack
FRONT_MAX_SIDE = 1800
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9&'\-]*[A-Za-z0-9]|[A-Za-z]{2,}")


def _otsu(arr: np.ndarray) -> int:
    hist = np.bincount(arr.ravel(), minlength=256).astype(float)
    total = hist.sum()
    cum, cum_mean = np.cumsum(hist), np.cumsum(hist * np.arange(256))
    w0 = cum / total
    w1 = 1 - w0
    m0 = np.divide(cum_mean, cum, out=np.zeros(256), where=cum > 0)
    m1 = np.divide(cum_mean[-1] - cum_mean, total - cum, out=np.zeros(256), where=(total - cum) > 0)
    return int(np.argmax(w0 * w1 * (m0 - m1) ** 2))


def plausible_word(tok: str) -> bool:
    letters = "".join(ch for ch in tok if ch.isalpha())
    if len(letters) < 3:
        return False
    if not any(ch in "aeiouyAEIOUY" for ch in letters):
        return False
    return not re.search(r"(.)\1\1", letters.lower())  # 'lll', 'iii' are usually bar or texture noise


def front_variants(img: Image.Image) -> list[tuple[str, Image.Image]]:
    """Image versions that make printed packaging text readable for OCR. Packaging text is often coloured on a
    coloured background (e.g. red on yellow) or light on dark, which plain grayscale loses. We therefore also use
    the colour channel with the strongest contrast, an Otsu-binarised version of it, and the inverted image."""
    rgb = ImageOps.exif_transpose(img).convert("RGB")
    longest = max(rgb.size)
    f = FRONT_MAX_SIDE / longest if longest > FRONT_MAX_SIDE else (1000 / longest if longest < 1000 else 1.0)
    if f != 1.0:
        rgb = rgb.resize((max(1, int(rgb.width * f)), max(1, int(rgb.height * f))), Image.LANCZOS)
    gray = ImageOps.autocontrast(ImageOps.grayscale(rgb), cutoff=1)
    chans = [np.asarray(c, dtype=np.uint8) for c in rgb.split()]
    best = max(chans, key=lambda c: float(c.std()))
    best_img = ImageOps.autocontrast(Image.fromarray(best), cutoff=1)
    t = _otsu(np.asarray(best_img))
    binary = Image.fromarray(((np.asarray(best_img) > t) * 255).astype(np.uint8))
    out = [("gray", gray), ("inverted", ImageOps.invert(gray)), ("best_channel", best_img), ("binary", binary)]
    if cv2 is not None:  # local contrast (CLAHE) recovers text in shadowed or glare-washed parts of glossy packs
        lab = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2LAB)
        out.append(("clahe", Image.fromarray(cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(lab[:, :, 0]))))
    return out


def text_bands(img: Image.Image, max_bands: int = 14) -> list[tuple[Image.Image, float]]:
    """Find horizontal bands that contain text and return each as a clean, dark-on-light crop.

    Packaging puts the brand and product name in large letters on coloured backgrounds; whole-page OCR often treats
    such areas as pictures and skips them. Here text is located with simple computer-vision cues instead:
      - horizontal intensity gradients |dI/dx| (letters have many vertical strokes; plain colour areas have none),
      - a row profile of strong-gradient pixels, split into bands where the profile is high,
      - per band: crop to the columns that contain strokes, pick the colour channel with the most contrast,
        binarise with Otsu's threshold and invert if needed so the minority (text) pixels are black,
      - rescale each band so letters are about 60 px tall, the size Tesseract reads best.
    Returns (crop, scale) pairs; scale converts heights in the crop back to the original image."""
    rgb = ImageOps.exif_transpose(img).convert("RGB")
    longest = max(rgb.size)
    if longest > FRONT_MAX_SIDE:
        f0 = FRONT_MAX_SIDE / longest
        rgb = rgb.resize((max(1, int(rgb.width * f0)), max(1, int(rgb.height * f0))), Image.LANCZOS)
    chans = np.stack([np.asarray(c, dtype=float) for c in rgb.split()])
    gx = np.abs(np.diff(chans, axis=2)).max(axis=0)  # strongest horizontal change over the three colour channels
    strong = gx > max(40.0, float(np.percentile(gx, 90)))
    prof = strong.mean(axis=1)
    prof = np.convolve(prof, np.ones(5) / 5, mode="same")
    on = prof > max(0.015, float(prof.mean()) * 0.6)
    bands, start = [], None
    for y, v in enumerate(np.append(on, False)):
        if v and start is None:
            start = y
        elif not v and start is not None:
            if y - start >= 10:
                bands.append((start, y))
            start = None
    merged: list[list[int]] = []
    for b in bands:  # join bands separated by tiny gaps (e.g. between the ascenders and the body of a word)
        if merged and b[0] - merged[-1][1] <= 4:
            merged[-1][1] = b[1]
        else:
            merged.append(list(b))
    merged.sort(key=lambda b: -(b[1] - b[0]))
    out = []
    for y0, y1 in merged[:max_bands]:
        y0, y1 = max(0, y0 - 4), min(rgb.height, y1 + 4)
        cols = np.flatnonzero(strong[y0:y1].any(axis=0))
        if len(cols) < 4:
            continue
        x0, x1 = max(0, cols[0] - 8), min(rgb.width, cols[-1] + 10)
        crop = chans[:, y0:y1, x0:x1]
        ch = crop[int(np.argmax([c.std() for c in crop]))]
        lo, hi = np.percentile(ch, 1), np.percentile(ch, 99)
        if hi - lo < 30:
            continue
        ch8 = np.clip((ch - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
        t = _otsu(ch8)
        dark = ch8 <= t
        text_is_dark = dark.mean() < 0.5
        binary = np.where(dark == text_is_dark, 0, 255).astype(np.uint8)
        band = Image.fromarray(binary)
        scale = 70.0 / max(1, y1 - y0)
        scale = min(3.0, max(0.25, scale))
        band = band.resize((max(1, int(band.width * scale)), max(1, int(band.height * scale))), Image.LANCZOS)
        band = ImageOps.expand(band, border=20, fill=255)
        out.append((band, scale))
    return out


def read_front(img: Image.Image) -> dict:
    """OCR of the front of a package. Runs sparse-text OCR (psm 11) on several image versions and merges the words.
    Each word keeps the largest printed height seen: the biggest text on a pack is almost always the brand or the
    product name, so `prominent` lists words by size (a simple text-salience cue used for identification)."""
    merged: dict[str, dict] = {}
    texts: list[str] = []
    runs = 0

    def add(words: list[dict], name: str, height_scale: float = 1.0) -> None:
        for w in words:
            tok = w["text"].strip(".,:;!?()[]{}\"'*")
            if w["conf"] < 55 or not _WORD.fullmatch(tok):
                continue
            letters = sum(ch.isalpha() for ch in tok)
            if letters < 2 or letters / len(tok) < 0.5:
                continue
            key = tok.lower()
            h = w["height"] / height_scale
            cur = merged.get(key)
            if cur is None or h > cur["height"]:
                merged[key] = {"text": tok, "height": round(h), "conf": w["conf"], "variant": name}

    variants = dict(front_variants(img))
    for name in ("gray", "best_channel"):
        r = _run(variants[name], psm=11)
        runs += 1
        texts.append(r["text"])
        add(r["words"], name)
    half = variants["best_channel"]
    half = half.resize((max(1, half.width // 2), max(1, half.height // 2)), Image.LANCZOS)  # very large lettering reads better smaller
    r = _run(half, psm=11)
    runs += 1
    add(r["words"], "best_channel_half", 0.5)
    if "clahe" in variants:
        r = _run(variants["clahe"], psm=11)
        runs += 1
        texts.append(r["text"])
        add(r["words"], "clahe")
    for band, scale in text_bands(img):
        r = _run(band, psm=6)
        runs += 1
        if r["text"].strip():
            texts.append(r["text"])
        add(r["words"], "text_band", scale)
    words = sorted(merged.values(), key=lambda w: (-w["height"], -w["conf"]))
    # Largest printed words first, without OCR debris: fragments such as "Fi" or "yp" (under 3 letters, or no vowel)
    # come from logos, patterns and glare and must not steer identification.
    prominent = [w["text"] for w in words if plausible_word(w["text"])][:6]
    return {"text": "\n".join(t for t in texts if t.strip()), "words": words[:60], "prominent": prominent,
            "word_count": len(words), "variants": runs}
