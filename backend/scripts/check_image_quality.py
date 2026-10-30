"""Print the image-quality measurements for a folder of your own photos, to check or tune the thresholds in
app/ml/image_quality.py (QUALITY_THRESHOLDS) against real phone pictures.

    cd D:\\SmartPlateAI\\backend
    .\\.venv\\Scripts\\python.exe scripts\\check_image_quality.py "D:\\photos\\test_set"

Put clearly good photos and clearly bad ones (blurred, dark, tiny) in the folder; the good ones should come out
"good" or "fair" and the bad ones "poor". Nothing is changed or saved.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.ml import image_quality as Q  # noqa: E402
from app.ml.recognizer import ImageError, decode_upload  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: check_image_quality.py <folder>")
    files = sorted(p for p in Path(sys.argv[1]).rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    print(f"{'file':40} {'level':6} {'sharp':>7} {'bright':>7} {'contr':>6} {'clip':>5} {'glare':>5}  issues")
    for p in files:
        try:
            r = Q.assess(decode_upload(p.read_bytes()))
        except ImageError as exc:
            print(f"{p.name[:40]:40} ERROR  {exc.message}")
            continue
        m = r["metrics"]
        print(f"{p.name[:40]:40} {r['level']:6} {m['sharpness']:7.1f} {m['brightness']:7.1f} {m['contrast']:6.1f} "
              f"{m['clipped_share']:5.2f} {m['glare_share']:5.2f}  {', '.join(r['issues'])}")
    print("Thresholds:", Q.QUALITY_THRESHOLDS)


if __name__ == "__main__":
    main()
