"""Retail barcode (EAN-13, UPC-A, EAN-8) detection in a package photo, using only numpy and Pillow.

How it works (classic 1-D barcode reading):
  1. The photo is converted to grayscale and examined at several rotations (0, 90, 45 and -45 degrees), so tilted
     packs still produce scanlines that cross all the bars.
  2. Many horizontal scanlines are taken. Each line is lightly smoothed and binarised with two thresholds
     (line-global and local), then converted into run lengths (alternating dark bars and light spaces).
  3. A 95-module EAN-13/UPC-A (or 67-module EAN-8) symbol has a fixed structure of 59 (43) runs: start guard,
     6 (4) digits, middle guard, 6 (4) digits, end guard. Each candidate window of runs is checked for that
     structure, every digit is classified by comparing its 4 normalised widths with the GS1 patterns, and the
     leading EAN-13 digit is recovered from the L/G parity pattern. Both reading directions are tried.
  4. A code is reported only if its GS1 check digit is valid AND at least two scanlines agree. That makes a
     false read very unlikely; when nothing qualifies the result is "not found" (never a guess).
"""
from __future__ import annotations

from collections import Counter

import numpy as np
from PIL import Image, ImageOps

try:  # optional: OpenCV's barcode detector (pip install opencv-python-headless)
    import cv2 as _cv2  # type: ignore
except Exception:  # noqa: BLE001
    _cv2 = None

# Widths (in modules) of the L-code patterns for digits 0-9 (space, bar, space, bar).
L_WIDTHS = [(3, 2, 1, 1), (2, 2, 2, 1), (2, 1, 2, 2), (1, 4, 1, 1), (1, 1, 3, 2),
            (1, 2, 3, 1), (1, 1, 1, 4), (1, 3, 1, 2), (1, 2, 1, 3), (3, 1, 1, 2)]
G_WIDTHS = [tuple(reversed(w)) for w in L_WIDTHS]
# Parity of the 6 left digits (0 = L, 1 = G) -> leading EAN-13 digit.
PARITY = {(0, 0, 0, 0, 0, 0): 0, (0, 0, 1, 0, 1, 1): 1, (0, 0, 1, 1, 0, 1): 2, (0, 0, 1, 1, 1, 0): 3, (0, 1, 0, 0, 1, 1): 4,
          (0, 1, 1, 0, 0, 1): 5, (0, 1, 1, 1, 0, 0): 6, (0, 1, 0, 1, 0, 1): 7, (0, 1, 0, 1, 1, 0): 8, (0, 1, 1, 0, 1, 0): 9}
_PATTERNS = np.array(L_WIDTHS + G_WIDTHS, dtype=float)  # rows 0-9 = L, 10-19 = G
MAX_SIDE = 1800
MAX_DIGIT_ERROR = 0.75  # summed absolute width error (in modules) above which a digit is rejected


def check_digit_ok(code: str) -> bool:
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def _runs(bits: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """bits: 1 = dark. Returns (colours, lengths) of consecutive runs."""
    change = np.flatnonzero(np.diff(bits)) + 1
    starts = np.concatenate(([0], change))
    ends = np.concatenate((change, [len(bits)]))
    return bits[starts], (ends - starts).astype(float)


def _digit(widths: np.ndarray, allow_g: bool) -> tuple[int, int] | None:
    """widths: 4 run lengths. Returns (digit, parity 0=L/R, 1=G) or None.
    Matching uses edge-to-similar-edge distances (a+b, b+c, c+d), which do not change when blur or ink spread makes
    every bar wider and every space narrower; the raw widths only break the 1/7 and 2/8 ties."""
    total = widths.sum()
    if total <= 0:
        return None
    norm = widths * 7.0 / total
    sums = norm[:-1] + norm[1:]
    pats = _PATTERNS if allow_g else _PATTERNS[:10]
    pat_sums = pats[:, :-1] + pats[:, 1:]
    err = np.abs(pat_sums - sums).sum(axis=1) + 0.35 * np.abs(pats - norm).sum(axis=1)
    best = int(err.argmin())
    if err[best] > MAX_DIGIT_ERROR * 1.6:
        return None
    second = np.partition(err, 1)[1]
    if second - err[best] < 0.08:
        return None
    return best % 10, best // 10


def _guard_ok(widths: np.ndarray, module: float) -> bool:
    return bool(np.all(widths > 0.3 * module) and np.all(widths < 2.3 * module))


def _decode_window(colours: np.ndarray, lengths: np.ndarray, i: int, kind: str) -> str | None:
    """Decode the run window starting at index i (a dark run). Handles both reading directions: read backwards,
    the right half appears first and every digit pattern is mirrored (L/R widths read as G widths and vice versa)."""
    n_digits = 6 if kind == "ean13" else 4
    n_runs = 3 + 4 * n_digits + 5 + 4 * n_digits + 3
    if i + n_runs > len(lengths) or colours[i] != 1:
        return None
    w = lengths[i:i + n_runs]
    module = w.sum() / (95 if kind == "ean13" else 67)
    if module < 4.0:  # < 1 px per module before the 4x upsampling
        return None
    mid = 3 + 4 * n_digits
    if not (_guard_ok(w[0:3], module) and _guard_ok(w[mid:mid + 5], module) and _guard_ok(w[-3:], module)):
        return None
    first_half, second_half = [], []
    for k in range(n_digits):
        d = _digit(w[3 + 4 * k: 7 + 4 * k], allow_g=True)
        if d is None:
            return None
        first_half.append(d)
    for k in range(n_digits):
        s0 = mid + 5 + 4 * k
        d = _digit(w[s0:s0 + 4], allow_g=True)
        if d is None:
            return None
        second_half.append(d)
    p1 = tuple(p for _, p in first_half)
    p2 = tuple(p for _, p in second_half)
    if all(p == 1 for p in p1) and (kind == "ean13" or all(p == 1 for p in p2)):
        # read backwards: un-mirror
        right = [d for d, _ in reversed(first_half)]
        left_pairs = [(d, 1 - p) for d, p in reversed(second_half)]
    elif not any(p2):
        right = [d for d, _ in second_half]
        left_pairs = first_half
    else:
        return None
    left = [d for d, _ in left_pairs]
    parity = tuple(p for _, p in left_pairs)
    if kind == "ean13":
        first = PARITY.get(parity)
        if first is None:
            return None
        code = f"{first}{''.join(map(str, left))}{''.join(map(str, right))}"
    else:
        if any(parity):
            return None
        code = "".join(map(str, left + right))
    return code if check_digit_ok(code) else None


def _scan_line(values: np.ndarray) -> list[str]:
    found: list[str] = []
    # 4x linear upsampling gives sub-pixel run lengths, which matters for small or blurred barcodes
    x = np.arange(len(values))
    v = np.interp(np.linspace(0, len(values) - 1, len(values) * 4), x, values)
    lo, hi = np.percentile(v, 5), np.percentile(v, 95)
    if hi - lo < 40:  # no contrast on this line
        return found
    thresholds = [np.full_like(v, (lo + hi) / 2)]
    for win in (max(31, len(v) // 40) | 1, max(61, len(v) // 12) | 1):
        pad = win // 2
        padded = np.pad(v, pad, mode="edge")
        cs = np.cumsum(np.concatenate(([0.0], padded)))
        local = (cs[win:] - cs[:-win]) / win
        thresholds.append(local[:len(v)])
    seen: set[str] = set()
    for thr in thresholds:
        colours, lengths = _runs((v < thr).astype(np.int8))
        for i in np.flatnonzero(colours == 1):
            for kind in ("ean13", "ean8"):
                code = _decode_window(colours, lengths, int(i), kind)
                if code and code not in seen:
                    seen.add(code)
                    found.append(code)
    return found


def _prepare(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(ImageOps.exif_transpose(img))
    longest = max(g.size)
    if longest > MAX_SIDE:
        f = MAX_SIDE / longest
        g = g.resize((max(1, int(g.width * f)), max(1, int(g.height * f))), Image.BILINEAR)
    return g


def _scan_votes(g: Image.Image, angles: tuple[int, ...], lines: int) -> tuple[Counter, dict]:
    votes: Counter = Counter()
    angle_of: dict[str, int] = {}
    for angle in angles:
        im = g if angle == 0 else g.rotate(angle, expand=True, fillcolor=255, resample=Image.BILINEAR)
        arr = np.asarray(im, dtype=float)
        h = arr.shape[0]
        step = max(1, h // lines)
        for y in range(step // 2, h - 1, step):
            row = arr[max(0, y - 1):y + 2].mean(axis=0)  # average 3 rows to reduce noise
            for code in set(_scan_line(row)):
                votes[code] += 1
                angle_of.setdefault(code, angle)
        if votes and votes.most_common(1)[0][1] >= 3:
            break  # confident enough; skip the remaining angles
    return votes, angle_of


def locate(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Find the most barcode-like region: many strong gradients in one direction and few in the other (parallel bars).
    Works on 16x16-pixel blocks of a 1600 px copy at 0 and 90 degrees; returns a box in original-image pixels."""
    g = ImageOps.grayscale(ImageOps.exif_transpose(img))
    f = 1600 / max(g.size) if max(g.size) > 1600 else 1.0
    small = np.asarray(g.resize((max(1, int(g.width * f)), max(1, int(g.height * f))), Image.BILINEAR), dtype=float)
    gx = np.abs(np.diff(small, axis=1))[:-1, :]
    gy = np.abs(np.diff(small, axis=0))[:, :-1]
    best = None
    for a, b in ((gx, gy), (gy, gx)):  # vertical bars, then horizontal bars
        bs = 16
        H, W = (a.shape[0] // bs) * bs, (a.shape[1] // bs) * bs
        if H == 0 or W == 0:
            return None
        A = a[:H, :W].reshape(H // bs, bs, W // bs, bs).mean(axis=(1, 3))
        B = b[:H, :W].reshape(H // bs, bs, W // bs, bs).mean(axis=(1, 3))
        score = A - B
        thr = max(12.0, float(score.max()) * 0.5)
        mask = score > thr
        if not mask.any():
            continue
        # largest 4-connected group of barcode-like blocks
        seen = np.zeros_like(mask)
        for sy, sx in zip(*np.nonzero(mask)):
            if seen[sy, sx]:
                continue
            stack, cells = [(sy, sx)], []
            seen[sy, sx] = True
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(cells) >= 4 and (best is None or len(cells) > best[0]):
                ys, xs = [c[0] for c in cells], [c[1] for c in cells]
                best = (len(cells), min(ys), max(ys), min(xs), max(xs))
    if best is None:
        return None
    _, y0, y1, x0, x1 = best
    bs = 16
    pad_x, pad_y = (x1 - x0 + 1) * bs * 0.25 + bs, (y1 - y0 + 1) * bs * 0.25 + bs
    box = (max(0, (x0 * bs - pad_x) / f), max(0, (y0 * bs - pad_y) / f),
           min(g.width, ((x1 + 1) * bs + pad_x) / f), min(g.height, ((y1 + 1) * bs + pad_y) / f))
    return tuple(int(v) for v in box)


def _opencv_reads(img: Image.Image) -> list[str]:
    """OpenCV's barcode detector (opencv-python 4.8+), if installed. Only check-digit-valid retail codes are kept."""
    if _cv2 is None or not hasattr(_cv2, "barcode"):
        return []
    out = []
    rgb = np.asarray(ImageOps.exif_transpose(img).convert("RGB"))
    det = _cv2.barcode.BarcodeDetector()
    for arr in (rgb, np.ascontiguousarray(np.rot90(rgb))):
        try:
            res = det.detectAndDecodeWithType(_cv2.cvtColor(arr, _cv2.COLOR_RGB2BGR))
        except Exception:  # noqa: BLE001
            continue
        for v in (res[1] or ()):
            d = "".join(ch for ch in str(v) if ch.isdigit())
            if d and len(d) in (8, 12, 13) and check_digit_ok(d):
                out.append(d if len(d) != 12 else "0" + d)
    return out


def _result(votes: Counter, angle_of: dict, method: str) -> dict:
    best = [(c, n) for c, n in votes.most_common() if n >= 2]
    if not best:
        return {"status": "not_found", "candidates": dict(votes.most_common(3))}
    code, n = best[0]
    if len(best) > 1 and best[1][1] == n:
        return {"status": "ambiguous", "candidates": dict(best[:3])}
    fmt = "EAN-8" if len(code) == 8 else ("UPC-A" if code.startswith("0") else "EAN-13")
    return {"status": "found", "code": code[1:] if fmt == "UPC-A" else code, "format": fmt, "votes": n,
            "angle": angle_of.get(code, 0), "decoder": method}


def detect(img: Image.Image, angles: tuple[int, ...] = (0, 90, 45, -45), lines: int = 120) -> dict:
    """Returns {"status": "found", "code", "format", "votes", "decoder"} or {"status": "not_found" | "ambiguous"}.

    Attempts, in order, stopping at the first confident result:
      1. OpenCV's detector on the full photo (when installed);
      2. the scanline decoder on the whole photo (downscaled to 1800 px);
      3. the barcode-like region found by `locate`, cropped from the FULL-resolution photo and enlarged, so a small
         barcode in a large phone photo keeps enough pixels per bar; both decoders are tried on it.
    A code counts only with independent agreement: two scanlines, or two OpenCV reads (photo + crop), or one read
    from each decoder."""
    votes: Counter = Counter()
    angle_of: dict[str, int] = {}
    for c in _opencv_reads(img):
        votes[c] += 1
    v2, a2 = _scan_votes(_prepare(img), angles, lines)
    for c, n in v2.items():
        votes[c] += n
        angle_of.setdefault(c, a2[c])
    res = _result(votes, angle_of, "scanline" if v2 else "opencv")
    if res["status"] == "found":
        return res
    box = locate(img)
    if box is not None:
        crop = ImageOps.exif_transpose(img).crop(box)
        if crop.width < 900:  # enlarge small barcodes so each bar spans several pixels
            k = 900 / max(1, crop.width)
            crop = crop.resize((int(crop.width * k), int(crop.height * k)), Image.LANCZOS)
        for c in _opencv_reads(crop):
            votes[c] += 1
        v3, a3 = _scan_votes(_prepare(crop), (0, 90, 15, -15), 80)
        for c, n in v3.items():
            votes[c] += n
            angle_of.setdefault(c, a3[c])
        res = _result(votes, angle_of, "region_crop")
        res["region"] = list(box)
    return res


# ------------------------------------------------------------------ encoder (used by tests and diagnostics)
def encode_ean13_modules(code: str) -> str:
    """Module string ('1' = bar) for a 13-digit EAN; used to render synthetic test images."""
    if len(code) == 12:
        code = "0" + code
    assert len(code) == 13 and check_digit_ok(code), "invalid EAN-13"
    parity = next(p for p, d in PARITY.items() if d == int(code[0]))
    out = "101"
    for k, ch in enumerate(code[1:7]):
        w = (G_WIDTHS if parity[k] else L_WIDTHS)[int(ch)]
        out += "".join(("0" if j % 2 == 0 else "1") * n for j, n in enumerate(w))
    out += "01010"
    for ch in code[7:]:
        w = L_WIDTHS[int(ch)]
        out += "".join(("1" if j % 2 == 0 else "0") * n for j, n in enumerate(w))
    return out + "101"


def render_ean13(code: str, module_px: int = 3, height: int = 140, quiet: int = 12) -> Image.Image:
    mods = encode_ean13_modules(code)
    w = (len(mods) + 2 * quiet) * module_px
    arr = np.full((height, w), 255, dtype=np.uint8)
    for i, m in enumerate(mods):
        if m == "1":
            x = (i + quiet) * module_px
            arr[:, x:x + module_px] = 0
    return Image.fromarray(arr, "L").convert("RGB")
