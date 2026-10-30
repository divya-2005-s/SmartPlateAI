"""Show every step of packaged-food recognition for your own photos, to see exactly where identification fails.

    cd D:\\SmartPlateAI\\backend
    .\\.venv\\Scripts\\python.exe scripts\\diagnose_packaged.py "C:\\photos\\maggi_front.jpg" "C:\\photos\\maggi_back.jpg"
    .\\.venv\\Scripts\\python.exe scripts\\diagnose_packaged.py front.jpg back.jpg --with-openai   (one paid OpenAI call)

Steps printed: dataset status, back-label OCR quality, front-of-pack words (largest first), barcode decoded from the
bars, barcode digits read as text, dataset match with its reason and candidates, and the Open Food Facts lookup
(free; needs internet). No API keys are printed. Nothing is saved.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.api.routes import packaged as route  # noqa: E402
from app.ml.recognizer import decode_upload  # noqa: E402
from app.services import ocr  # noqa: E402
from app.services import openfoodfacts as off  # noqa: E402
from app.services.label_parser import parse_label  # noqa: E402
from app.services.packaged import PackagedFoodData, parse_quantity_g  # noqa: E402


def load(path: str | None):
    return decode_upload(Path(path).read_bytes()) if path else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("front", nargs="?", help="photo of the front of the pack")
    ap.add_argument("back", nargs="?", help="photo of the back label")
    ap.add_argument("--with-openai", action="store_true", help="also run the OpenAI package reading (paid)")
    a = ap.parse_args()
    if not (a.front or a.back):
        sys.exit("Give at least one photo.")
    front, back = load(a.front), load(a.back)

    data = PackagedFoodData()
    print("1. Dataset:", "loaded, %d products" % len(data.products) if data.load() else f"NOT loaded ({data.error})")
    if data.detected:
        print("   barcode column:", data.detected.get("product_columns", {}).get("barcode"), "| file:", data.detected.get("products_csv"))
    print("   Tesseract:", ocr.tesseract_cmd() or "NOT FOUND (set TESSERACT_CMD in backend/.env)")

    back_text = ""
    if back is not None:
        t = time.time()
        o = ocr.ocr_image(back)
        back_text = o["text"]
        print(f"2. Back OCR: quality={o['quality']} words={o['word_count']} confidence={o['confidence']} rotation={o['rotation']} "
              f"({time.time() - t:.1f}s)")
        print("   first lines:", " | ".join(back_text.splitlines()[:4])[:200])
    front_text, prominent = "", []
    if front is not None:
        t = time.time()
        fr = ocr.read_front(front)
        front_text, prominent = fr["text"], fr["prominent"]
        print(f"3. Front OCR ({fr['variants']} passes, {time.time() - t:.1f}s): largest words = {prominent}")
        print("   all words:", ", ".join(w["text"] for w in fr["words"][:25]))
    t = time.time()
    bc = route.detect_barcode(back, front)
    print(f"4. Barcode from the bars: {bc.get('status')} {bc.get('code') or ''} {bc.get('format') or ''} "
          f"votes={bc.get('votes')} ({time.time() - t:.1f}s)")
    label = parse_label(back_text)
    print("   Barcode digits read as text:", label["identifiers"]["barcode_digits"])
    code = bc.get("code") or label["identifiers"]["barcode_digits"]

    ai_identity = ""
    if a.with_openai:
        reading = route.run_package_reading(front, back)
        print("5. OpenAI package reading:", reading.get("status"), reading.get("reason") or "")
        if reading.get("status") == "ok":
            f = reading["front"]
            ai_identity = " ".join(filter(None, [f.get("brand"), f.get("product_name"), f.get("variant")]))
            print("   read:", ai_identity)
    else:
        print("5. OpenAI package reading: skipped (add --with-openai)")

    text = "\n".join(filter(None, [ai_identity, " ".join(prominent), front_text, back_text]))
    ident = "\n".join(filter(None, [ai_identity, " ".join(prominent), front_text])) or None
    if data.loaded:
        m = data.match(text, barcode=code, net_quantity_g=parse_quantity_g(label["identifiers"].get("net_quantity")), identity_text=ident)
        print(f"6. Dataset match: {m['status']} (method={m.get('method')}, score={m['confidence']})")
        print("   reason:", m["reason"])
        for c in m["candidates"][:5]:
            ev = c["evidence"]
            print(f"   - {c['name']} [{c.get('brand')}] score={c['score']} matched={ev.get('matched_words')} "
                  f"missing={ev.get('missing_words')} conflicts={ev.get('conflicting_words')}")
        hits = data.search(" ".join(prominent[:3])) if prominent else []
        print("   dataset search for the largest words:", [h["name"] for h in hits[:5]] or "nothing")
    if not off.enabled():
        print("7. Open Food Facts: disabled (OPENFOODFACTS_ENABLED=false)")
        return
    if code:
        r = off.by_barcode(code)
        print("7. Open Food Facts by barcode:", r.get("status"), (r.get("product") or {}).get("name") or r.get("message", ""))
    q = ai_identity or " ".join(prominent[:5])
    if q:
        r = off.search(q, None, verify_text=text)
        print(f"   Open Food Facts name search '{q}':", r.get("status"), (r.get("product") or {}).get("name") or r.get("message", ""))
        for c in r.get("candidates", [])[:5]:
            print(f"   - {c.get('name')} [{c.get('brand')}] barcode={c.get('code')} verified={c.get('verified_against_label')}")
    print(json.dumps({"done": True}))


if __name__ == "__main__":
    main()
