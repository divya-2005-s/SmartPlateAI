"""Diagnose food-recognition decisions on real images, comparing the decision rule before and after the
classifier-agreement check. Uses the production model exactly as the API does (same decode, resize and gates).

Never touches the test split. Thresholds are NOT changed by this script; it only measures.

Examples (from D:\\SmartPlateAI\\backend):
  # 1) exact images that were misclassified (files or folders)
  .\\.venv\\Scripts\\python.exe scripts\\diagnose_recognition.py --images "C:\\Users\\me\\Pictures\\wrong1.jpg" "D:\\misclassified"
  # 2) validation sample (non-augmented, 40 per class) + a folder of foods that are NOT among the 24 classes
  .\\.venv\\Scripts\\python.exe scripts\\diagnose_recognition.py --val-per-class 40 --unsupported-dir D:\\unsupported_foods
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.ml.recognizer import FoodRecognizer, decode_upload  # noqa: E402
from app.ml.rejection import wilson_interval  # noqa: E402

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MANIFEST = BACKEND_DIR / "data_prep" / "split_manifest.csv"


def list_images(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(q for q in p.rglob("*") if q.suffix.lower() in IMG_EXT)
        elif p.is_file():
            out.append(p)
        else:
            print(f"WARNING: not found: {p}")
    return out


def analyse(rec, items: list[tuple[Path, str | None, str]]) -> list[dict]:
    rows, t0 = [], time.time()
    for n, (path, expected, group) in enumerate(items, 1):
        row = {"group": group, "path": str(path), "expected": expected or ""}
        try:
            r = rec.analyze_image(decode_upload(Path(path).read_bytes()))
        except Exception as exc:  # noqa: BLE001
            row.update(decision="error", decision_before="error", reason=str(getattr(exc, "code", type(exc).__name__)))
            rows.append(row)
            continue
        s = r["signals"]
        row.update(decision=r["decision"], decision_before=s.get("decision_without_agreement_check", r["decision"]),
                   reason=r.get("reason") or "", top1=r["top_k"][0]["food"], top1_score=r["top_k"][0]["score"],
                   top2=r["top_k"][1]["food"], top2_score=r["top_k"][1]["score"], margin=round(r["margin"], 4),
                   nearest_feature_class=s.get("nearest_feature_class") or "", feature_distance=round(s.get("feature_distance") or 0, 1),
                   imagenet_food_mass=round(s.get("imagenet_food_mass") or 0, 4))
        row["top1_correct"] = "" if not expected else str(row["top1"] == expected)
        rows.append(row)
        if n % 50 == 0:
            print(f"  {n}/{len(items)} ({n / (time.time() - t0):.1f} img/s)")
    return rows


def pct(k: int, n: int) -> str:
    if n == 0:
        return "n/a"
    lo, hi = wilson_interval(k, n)
    return f"{k}/{n} = {k / n:.1%} (95% CI {lo:.1%}-{hi:.1%})"


def summarise(rows: list[dict]) -> list[str]:
    L: list[str] = []
    groups = defaultdict(list)
    for r in rows:
        groups[r["group"]].append(r)
    for g, rs in groups.items():
        ok = [r for r in rs if r["decision"] != "error"]
        L += [f"## {g} (n={len(rs)}, unreadable={len(rs) - len(ok)})", ""]
        for label, key in (("before (no agreement check)", "decision_before"), ("after (with agreement check)", "decision")):
            acc = [r for r in ok if r[key] == "accept"]
            line = f"- **{label}**: accepted with a food name {pct(len(acc), len(ok))}"
            if g == "validation":
                right = sum(r["top1_correct"] == "True" for r in acc)
                wrong = len(acc) - right
                line += f"; accuracy among accepted {pct(right, len(acc))}; wrong names shown {pct(wrong, len(ok))}"
            counts = defaultdict(int)
            for r in ok:
                counts[r[key]] += 1
            L.append(line + "; " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        L.append("")
        if g == "validation":
            per = defaultdict(lambda: [0, 0, 0, 0])  # n, accepted_before, accepted_after, wrong_after
            for r in ok:
                c = per[r["expected"]]
                c[0] += 1
                c[1] += r["decision_before"] == "accept"
                c[2] += r["decision"] == "accept"
                c[3] += r["decision"] == "accept" and r["top1_correct"] != "True"
            L += ["| class | n | accepted before | accepted after | wrong names after |", "|---|---|---|---|---|"]
            for k in sorted(per):
                n, a, b, w = per[k]
                L.append(f"| {k} | {n} | {a} | {b} | {w} |")
            L.append("")
        if g != "validation":
            L += ["| image | decision after | before | top-1 (score) | top-2 (score) | nearest feature class | reason |", "|---|---|---|---|---|---|---|"]
            for r in ok[:200]:
                L.append(f"| {Path(r['path']).name} | {r['decision']} | {r['decision_before']} | {r['top1']} ({r['top1_score']}) | "
                         f"{r['top2']} ({r['top2_score']}) | {r['nearest_feature_class']} | {r['reason']} |")
            L.append("")
    return L


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", nargs="*", default=[], help="specific images or folders (e.g. ones that were misclassified)")
    ap.add_argument("--val-per-class", type=int, default=0, help="non-augmented VALIDATION images per class (test split never used)")
    ap.add_argument("--unsupported-dir", help="folder of foods that are NOT among the 24 supported classes")
    ap.add_argument("--nonfood-dir", help="folder of non-food photos")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rec = FoodRecognizer()
    if not rec.load():
        sys.exit(f"Model not ready: {rec.status_message}")
    items: list[tuple[Path, str | None, str]] = [(p, None, "your images") for p in list_images(args.images)]
    if args.val_per_class:
        import pandas as pd  # noqa: PLC0415
        df = pd.read_csv(MANIFEST, usecols=["image_path", "food", "new_split", "is_augmented_copy"])
        val = df[(df.new_split == "val") & df.is_augmented_copy.astype(str).str.lower().isin(["false", "0"])]
        val = val.groupby("food", group_keys=False).apply(lambda g: g.sample(min(len(g), args.val_per_class), random_state=args.seed))
        items += [(Path(p), f, "validation") for p, f in zip(val.image_path, val.food)]
    if args.unsupported_dir:
        items += [(p, None, "unsupported foods") for p in list_images([args.unsupported_dir])]
    if args.nonfood_dir:
        items += [(p, None, "non-food") for p in list_images([args.nonfood_dir])]
    if not items:
        sys.exit("Nothing to analyse. Pass --images, --val-per-class, --unsupported-dir or --nonfood-dir.")

    print(f"Analysing {len(items)} images (class-agreement check: {'on' if rec.require_agreement else 'OFF'}) ...")
    rows = analyse(rec, items)
    out = BACKEND_DIR / "reports" / "recognition_diagnostics" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(out / "per_image.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    th = rec.thresholds
    report = ["# Recognition diagnostics", "", f"Model: `{rec.model_dir}` | thresholds unchanged: {th}", "",
              "'before' = decision rule without the classifier-agreement check; 'after' = current API behaviour.",
              "Validation images may include the half used to calibrate the thresholds, so validation rates are slightly optimistic.", "",
              *summarise(rows)]
    (out / "report.md").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print(f"\nWrote {out / 'report.md'} and per_image.csv")


if __name__ == "__main__":
    main()
