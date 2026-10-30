"""
SmartPlateAI - Phase 1 dataset audit (READ-ONLY).

What it does
  * Finds your dataset CSVs (only inside the folders you allow).
  * Audits each CSV: schema, missing values, label problems, duplicates, impossible values.
  * Scans every food image listed in the food CSV: exists? decodes? exact / near duplicates?
    Do duplicates cross the train/validation/test splits?
  * Writes reports into backend\\reports\\. It never moves, renames, edits or deletes your data.

Run:  python scripts\\audit_datasets.py --help
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from itertools import islice
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

# ----------------------------------------------------------------------------- paths
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
REPORTS_DIR = BACKEND_DIR / "reports"

TARGETS = {
    "food_csv": "final_food_nutrient_dataset.csv",
    "packaged_csv": "packaged_foods_india_clean.csv",
    "additives_csv": "packaged_food_additives.csv",
    "additive_ref_csv": "additive_reference_populated.csv",
}
SKIP_DIRS = {"node_modules", ".git", ".venv", ".venv-audit", "venv", "__pycache__", "dist",
             "build", ".idea", ".vscode", "images"}

BAD_TOKENS = {"", "nan", "none", "null", "unknown", "other", "unlabeled", "unlabelled", "?", "n/a", "na"}
SPLIT_ALIASES = {"train": "train", "training": "train", "valid": "val", "validation": "val",
                 "val": "val", "test": "test", "testing": "test"}
AUG_RE = re.compile(r"^(?:rotated_by_\d+|translation|flipped|flip|zoom|shear)_", re.IGNORECASE)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}


# ----------------------------------------------------------------------------- report helpers
def md_table(df: pd.DataFrame, max_rows: int = 40) -> str:
    if df is None or len(df) == 0:
        return "_(none)_\n"
    d = df.head(max_rows).copy()
    d = d.astype(object).where(d.notna(), "")
    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, r in d.iterrows():
        lines.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in r) + " |")
    if len(df) > max_rows:
        lines.append(f"\n_... {len(df) - max_rows} more rows not shown._")
    return "\n".join(lines) + "\n"


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.findings: list[tuple[str, str]] = []
        self.summary: dict = {}

    def h(self, text: str, level: int = 2) -> None:
        self.lines += ["", f"{'#' * level} {text}", ""]

    def p(self, text: str) -> None:
        self.lines += [text, ""]

    def bullets(self, items: list[str]) -> None:
        self.lines += [f"- {i}" for i in items] + [""]

    def table(self, df: pd.DataFrame, max_rows: int = 40) -> None:
        self.lines += [md_table(df, max_rows)]

    def finding(self, severity: str, text: str) -> None:
        self.findings.append((severity, text))

    def render(self, meta: dict) -> str:
        order = {"HIGH": 0, "MEDIUM": 1, "INFO": 2}
        head = ["# SmartPlateAI - Dataset Audit Report", "",
                f"Generated: {meta['generated']}  ", f"Script version: {meta['version']}", "",
                "## Key findings", ""]
        for sev, txt in sorted(self.findings, key=lambda x: order.get(x[0], 9)):
            head.append(f"- **[{sev}]** {txt}")
        head.append("")
        return "\n".join(head + self.lines) + "\n"


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, float) and np.isnan(o):
        return None
    return o


# ----------------------------------------------------------------------------- discovery
def find_files(roots: list[Path], names: dict[str, str], max_depth: int) -> dict[str, list[Path]]:
    wanted = {v.lower(): k for k, v in names.items()}
    found: dict[str, list[Path]] = {k: [] for k in names}
    for root in roots:
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).parts) - base_depth
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS] if depth < max_depth else []
            for fn in filenames:
                key = wanted.get(fn.lower())
                if key:
                    found[key].append(Path(dirpath) / fn)
    return found


def resolve_paths(args, rep: Report) -> dict[str, Path | None]:
    roots = [Path(r) for r in ([str(PROJECT_ROOT)] + (args.extra_root or []))]
    rep.h("1. Dataset discovery")
    rows = [{"searched_root": str(r), "exists": r.is_dir()} for r in roots]
    rep.p(f"Search depth limit: {args.max_depth} folder levels. Only these roots were searched "
          "(your whole computer is never scanned):")
    rep.table(pd.DataFrame(rows))
    found = find_files(roots, TARGETS, args.max_depth)
    resolved: dict[str, Path | None] = {}
    explicit = {"food_csv": args.food_csv, "packaged_csv": args.packaged_csv,
                "additives_csv": args.additives_csv, "additive_ref_csv": args.additive_ref_csv}
    out_rows = []
    for key, fname in TARGETS.items():
        chosen: Path | None = None
        note = ""
        if explicit[key]:
            p = Path(explicit[key])
            chosen = p if p.is_file() else None
            note = "explicit path" if chosen else "explicit path NOT FOUND"
        elif len(found[key]) == 1:
            chosen, note = found[key][0], "found"
        elif len(found[key]) > 1:
            note = "AMBIGUOUS - several copies found; pass the exact path with --" + key.replace("_", "-")
            rep.finding("HIGH", f"{fname}: several copies found: " + "; ".join(str(x) for x in found[key]))
        else:
            note = "NOT FOUND"
        if chosen is None and key in ("food_csv",):
            rep.finding("HIGH", f"{fname} was not located ({note}). Tell me where it is, or pass --food-csv.")
        resolved[key] = chosen
        out_rows.append({"dataset": fname, "status": note, "path": str(chosen) if chosen else ""})
    rep.table(pd.DataFrame(out_rows))
    return resolved


# ----------------------------------------------------------------------------- generic CSV helpers
def load_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Could not decode {path}")


def schema_table(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "column": df.columns,
        "dtype": [str(t) for t in df.dtypes],
        "non_null": df.notna().sum().values,
        "missing": df.isna().sum().values,
        "missing_%": (df.isna().mean().values * 100).round(2),
        "unique": [df[c].nunique(dropna=True) for c in df.columns],
    })


def pick(df: pd.DataFrame, *aliases: str) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for a in aliases:
        if a.lower() in lower:
            return lower[a.lower()]
    return None


def norm_label(s: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


# ----------------------------------------------------------------------------- image scan
def dhash(im: Image.Image, size: int = 8) -> int:
    g = im.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return v


def scan_one(path: str) -> dict:
    out = {"exists": False, "bytes": 0, "sha256": "", "width": 0, "height": 0, "format": "",
           "mode": "", "decode_ok": False, "error": "", "dhash": ""}
    try:
        p = Path(path)
        if not p.is_file():
            out["error"] = "missing"
            return out
        out["exists"] = True
        data = p.read_bytes()
        out["bytes"] = len(data)
        out["sha256"] = hashlib.sha256(data).hexdigest()
        with Image.open(io.BytesIO(data)) as im:
            out["width"], out["height"] = im.size
            out["format"] = im.format or ""
            out["mode"] = im.mode
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.draft("RGB", (160, 160))  # fast reduced-size decode for JPEG; ignored for other formats
            out["dhash"] = f"{dhash(im):016x}"
        out["decode_ok"] = True
    except Exception as exc:  # noqa: BLE001 - we want to record any failure
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def run_scan(paths: list[str], workers: int) -> list[dict]:
    total = len(paths)
    results: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, res in enumerate(pool.map(scan_one, paths, chunksize=16), 1):
            results.append(res)
            if i % 2000 == 0 or i == total:
                rate = i / max(time.time() - t0, 1e-6)
                eta = (total - i) / max(rate, 1e-6)
                print(f"  scanned {i:,}/{total:,} images  ({rate:,.0f}/s, ~{eta/60:.1f} min left)", flush=True)
    return results


class DSU:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def popcount64(x: np.ndarray) -> np.ndarray:
    x = x - ((x >> np.uint64(1)) & np.uint64(0x5555555555555555))
    x = (x & np.uint64(0x3333333333333333)) + ((x >> np.uint64(2)) & np.uint64(0x3333333333333333))
    x = (x + (x >> np.uint64(4))) & np.uint64(0x0F0F0F0F0F0F0F0F)
    return (x * np.uint64(0x0101010101010101)) >> np.uint64(56)


def near_duplicate_groups(hashes: pd.Series, max_dist: int, bucket_cap: int) -> tuple[pd.Series, int]:
    """Group images whose 64-bit dHash differ in <= max_dist bits (max_dist <= 3 uses 4 x 16-bit buckets)."""
    gid = pd.Series(-1, index=hashes.index, dtype="int64")
    valid = hashes[hashes.astype(str).str.len() == 16]
    if len(valid) < 2:
        return gid, 0
    vals = np.array([int(h, 16) for h in valid.values], dtype=np.uint64)
    dsu = DSU(len(vals))
    skipped = 0
    with np.errstate(over="ignore"):
        for chunk in range(4):
            keys = (vals >> np.uint64(16 * chunk)) & np.uint64(0xFFFF)
            order = np.argsort(keys, kind="stable")
            bounds = np.flatnonzero(np.diff(keys[order])) + 1
            for members in np.split(order, bounds):
                m = len(members)
                if m < 2:
                    continue
                if m > bucket_cap:
                    skipped += 1
                    continue
                arr = vals[members]
                for i in range(m - 1):
                    d = popcount64(arr[i] ^ arr[i + 1:])
                    for j in np.flatnonzero(d <= max_dist):
                        dsu.union(int(members[i]), int(members[i + 1 + j]))
    roots = np.array([dsu.find(i) for i in range(len(vals))])
    counts = Counter(roots.tolist())
    mapping = {r: k for k, r in enumerate(r for r, c in counts.items() if c > 1)}
    for pos, r in enumerate(roots):
        if r in mapping:
            gid.loc[valid.index[pos]] = mapping[r]
    return gid, skipped


def group_leakage(df: pd.DataFrame, gcol: str, split_col: str, label_col: str) -> dict:
    g = df[df[gcol] >= 0] if df[gcol].dtype.kind in "iu" else df[df[gcol].notna()]
    if len(g) == 0:
        return {"groups": 0, "images_in_groups": 0, "groups_cross_split": 0, "images_in_cross_split_groups": 0,
                "groups_cross_label": 0, "test_images_with_train_or_val_twin": 0}
    agg = g.groupby(gcol).agg(n=(split_col, "size"), ns=(split_col, "nunique"), nl=(label_col, "nunique"))
    cross = agg[agg.ns > 1].index
    test_leak = g[(g[split_col] == "test") & g[gcol].isin(cross)]
    twin_ok = 0
    if len(test_leak):
        splits_by_group = g.groupby(gcol)[split_col].agg(set)
        twin_ok = int(test_leak[gcol].map(lambda k: bool(splits_by_group[k] - {"test"})).sum())
    return {"groups": int(len(agg)), "images_in_groups": int(agg.n.sum()),
            "groups_cross_split": int((agg.ns > 1).sum()),
            "images_in_cross_split_groups": int(agg.loc[agg.ns > 1, "n"].sum()),
            "groups_cross_label": int((agg.nl > 1).sum()),
            "test_images_with_train_or_val_twin": twin_ok}


# ----------------------------------------------------------------------------- food image CSV audit
def audit_food(df: pd.DataFrame, args, rep: Report) -> None:
    rep.h("2. Food image dataset (final_food_nutrient_dataset.csv)")
    rep.p(f"Rows: **{len(df):,}**, columns: **{df.shape[1]}**.")
    core = ["image_id", "image_name", "image_path", "food", "class", "condition", "source_dataset", "split", "fdc_id"]
    miss_core = [c for c in core if c not in df.columns]
    if miss_core:
        rep.finding("HIGH", f"Food CSV is missing expected columns: {miss_core}. Later steps need them.")
    nutrient_cols = [c for c in df.columns if re.search(r"_(g|mg|ug|kcal)$", c)]
    rep.p(f"Detected {len(nutrient_cols)} nutrient columns (by unit suffix): {', '.join(nutrient_cols)}")
    rep.h("2.1 Schema and missing values", 3)
    rep.table(schema_table(df), max_rows=60)
    rep.summary["food_rows"] = len(df)

    # ---- label hygiene
    rep.h("2.2 Label hygiene", 3)
    split_col = "split" if "split" in df.columns else None
    food_col = "food" if "food" in df.columns else None
    for col in [c for c in ("food", "class", "condition", "source_dataset", "split") if c in df.columns]:
        s = df[col].astype("string")
        stripped = s.str.strip()
        ws = int((s.notna() & (s != stripped)).sum())
        bad = int((stripped.isna() | stripped.str.lower().isin(BAD_TOKENS)).sum())
        variants: dict[str, set] = {}
        for v in s.dropna().unique():
            variants.setdefault(norm_label(v), set()).add(v)
        coll = {k: sorted(v) for k, v in variants.items() if len(v) > 1}
        rep.p(f"**{col}** - {s.nunique()} distinct values; leading/trailing-space values: {ws}; "
              f"empty/unknown-like values: {bad}; spelling/case collisions: {len(coll)}")
        if coll:
            rep.finding("MEDIUM", f"Column '{col}' has label spelling/case variants that should be merged: {coll}")
        if col in ("food", "class", "source_dataset", "split"):
            vc = s.value_counts(dropna=False).rename_axis(col).reset_index(name="count")
            rep.table(vc, max_rows=40)
    if split_col:
        unmapped = sorted({str(v) for v in df[split_col].dropna().unique()
                           if str(v).strip().lower() not in SPLIT_ALIASES})
        if unmapped:
            rep.finding("HIGH", f"Unrecognised split names: {unmapped}")
        df["_split"] = df[split_col].astype("string").str.strip().str.lower().map(SPLIT_ALIASES)
    else:
        df["_split"] = pd.NA

    # ---- class mapping
    rep.h("2.3 Food class mapping", 3)
    if food_col:
        foods = df[food_col].astype("string").str.strip()
        valid_mask = foods.notna() & ~foods.str.lower().isin(BAD_TOKENS)
        if (~valid_mask).any():
            rep.finding("HIGH", f"{int((~valid_mask).sum())} rows have an empty/unknown food label and must be excluded from training.")
        dv = df[valid_mask].copy()
        dv["_food"] = foods[valid_mask]
        names = sorted(dv["_food"].unique())
        rows = []
        for i, f in enumerate(names):
            sub = dv[dv["_food"] == f]
            row = {"class_id": i, "food": f, "n_images": len(sub)}
            for sp in ("train", "val", "test"):
                row[sp] = int((sub["_split"] == sp).sum())
            if "source_dataset" in sub:
                row["sources"] = ", ".join(sorted(sub["source_dataset"].astype(str).unique()))
            if "fdc_id" in sub:
                row["fdc_ids"] = ", ".join(str(x) for x in sorted(sub["fdc_id"].dropna().unique()))
                row["n_fdc_ids"] = int(sub["fdc_id"].nunique())
            flags = []
            if len(sub) < args.min_class_images:
                flags.append(f"LOW_DATA(<{args.min_class_images})")
            if any(row[sp] == 0 for sp in ("train", "val", "test")):
                flags.append("MISSING_SPLIT")
            if row.get("n_fdc_ids", 1) != 1:
                flags.append("FDC_NOT_UNIQUE")
            row["flags"] = "; ".join(flags) or "OK"
            rows.append(row)
        cm = pd.DataFrame(rows)
        rep.table(cm, max_rows=80)
        cm.to_csv(REPORTS_DIR / "class_mapping.csv", index=False)
        rep.summary["n_food_classes"] = len(cm)
        rep.summary["class_names"] = names
        counts = cm["n_images"]
        ratio = counts.max() / max(counts.min(), 1)
        rep.p(f"Class imbalance: largest class {counts.max():,} images, smallest {counts.min():,} "
              f"(ratio {ratio:.1f}x). Classes flagged LOW_DATA: {int(cm['flags'].str.contains('LOW_DATA').sum())}.")
        if ratio > 5:
            rep.finding("MEDIUM", f"Strong class imbalance ({ratio:.1f}x). Training needs class weights or balanced sampling, "
                                  "and the report must use macro-averaged metrics.")
        if "fdc_id" in dv:
            by_fdc = dv.groupby("fdc_id")["_food"].nunique()
            if (by_fdc > 1).any():
                rep.finding("HIGH", f"These FDC ids map to more than one food: {by_fdc[by_fdc > 1].index.tolist()}")
        if "class" in dv and "source_dataset" in dv:
            src_by_food = dv.groupby("_food")["source_dataset"].nunique()
            only_one_src = (dv.groupby("source_dataset")["_food"].nunique())
            rep.p("Number of distinct foods contributed by each image source:")
            rep.table(only_one_src.rename_axis("source_dataset").reset_index(name="foods"))
            single = [f for f, n in src_by_food.items() if n == 1]
            if single:
                rep.finding("MEDIUM", "Source confounding: "
                            f"{len(single)} of {len(src_by_food)} foods come from a single image source, so a model can "
                            "partly learn the dataset's photo style instead of the food. Interpret test accuracy with care.")
        # stratification check
        if dv["_split"].notna().any():
            overall = dv["_food"].value_counts(normalize=True)
            dev = []
            for sp in ("train", "val", "test"):
                share = dv.loc[dv["_split"] == sp, "_food"].value_counts(normalize=True).reindex(overall.index).fillna(0)
                dev.append((share - overall).abs().max() * 100)
            rep.p(f"Largest class-share deviation from overall: train {dev[0]:.2f} pp, val {dev[1]:.2f} pp, test {dev[2]:.2f} pp "
                  "(small = splits are stratified).")
        sc = dv["_split"].value_counts()
        rep.p("Split sizes: " + ", ".join(f"{k}={v:,}" for k, v in sc.items()))

    # ---- condition / freshness
    rep.h("2.4 Condition (freshness) labels", 3)
    if "condition" in df.columns:
        cond = df["condition"].astype("string").str.strip()
        cond_bad = cond.isna() | cond.str.lower().isin(BAD_TOKENS)
        cls = df["class"].astype("string").str.lower() if "class" in df.columns else pd.Series(pd.NA, index=df.index, dtype="string")
        implied = pd.Series(pd.NA, index=df.index, dtype="string")
        implied[cls.str.contains("rotten", na=False)] = "Rotten"
        implied[cls.str.contains("fresh", na=False) & implied.isna()] = "Fresh"
        recoverable = cond_bad & implied.notna()
        contradiction = (~cond_bad) & implied.notna() & (cond.str.lower() != implied.str.lower())
        rep.p(f"Rows whose `condition` is empty/Unknown: **{int(cond_bad.sum()):,}**. Of these, **{int(recoverable.sum()):,}** have a class name "
              f"that states fresh/rotten (heuristic: class contains 'fresh' or 'rotten'), so the label could be recovered. "
              f"Rows where `condition` contradicts the class name: **{int(contradiction.sum())}**.")
        if recoverable.sum():
            rep.finding("MEDIUM", f"{int(recoverable.sum()):,} images are labelled condition=Unknown but their class name already says Fresh/Rotten. "
                                  "These can be used for the freshness model after you confirm the heuristic.")
        if contradiction.sum():
            rep.finding("HIGH", f"{int(contradiction.sum())} rows have a condition label that contradicts the class name.")
        final = cond.where(~cond_bad, implied).fillna("Unknown")
        df["_cond_final"] = final
        if food_col:
            ct = pd.crosstab(df[food_col], df["_cond_final"])
            ct.insert(0, "food", ct.index)
            rep.p("Condition counts per food after recovery (Unknown = no usable freshness label):")
            rep.table(ct.reset_index(drop=True), max_rows=60)
            ct.to_csv(REPORTS_DIR / "condition_audit.csv", index=False)
            fr = df[df["_cond_final"].isin(["Fresh", "Rotten"])]
            piv = fr.pivot_table(index=food_col, columns=["_cond_final", "_split"], values="image_name" if "image_name" in fr else food_col,
                                 aggfunc="size", fill_value=0)
            both = [f for f in fr[food_col].unique()
                    if {"Fresh", "Rotten"} <= set(fr.loc[fr[food_col] == f, "_cond_final"])]
            rep.p(f"Foods that have BOTH Fresh and Rotten examples (candidates for a freshness model): **{len(both)}** - {', '.join(sorted(both))}")
            rep.summary["freshness_foods"] = sorted(both)
            fr_rows = []
            for f in sorted(both):
                s = fr[fr[food_col] == f]
                r = {"food": f, "fresh": int((s["_cond_final"] == "Fresh").sum()), "rotten": int((s["_cond_final"] == "Rotten").sum())}
                for sp in ("train", "val", "test"):
                    r[f"{sp}_fresh"] = int(((s["_split"] == sp) & (s["_cond_final"] == "Fresh")).sum())
                    r[f"{sp}_rotten"] = int(((s["_split"] == sp) & (s["_cond_final"] == "Rotten")).sum())
                fr_rows.append(r)
            rep.table(pd.DataFrame(fr_rows), max_rows=60)
            no_cond = sorted(set(df[food_col].dropna().unique()) - set(both))
            rep.p(f"Foods with NO usable Fresh/Rotten pair (a freshness model cannot be trained or evaluated for them): {', '.join(no_cond)}")
            rep.summary["foods_without_freshness_labels"] = no_cond
        del piv
    else:
        rep.p("No `condition` column found - freshness model cannot be audited.")

    # ---- nutrients
    rep.h("2.5 Nutrient columns", 3)
    if nutrient_cols and food_col:
        rows = []
        for c in nutrient_cols:
            miss = df[c].isna()
            rows.append({"nutrient": c, "missing_rows": int(miss.sum()), "missing_%": round(miss.mean() * 100, 2),
                         "foods_with_missing": ", ".join(sorted(df.loc[miss, food_col].dropna().unique())) or "-",
                         "negative_values": int((df[c] < 0).sum())})
        nt = pd.DataFrame(rows)
        rep.table(nt[(nt.missing_rows > 0) | (nt.negative_values > 0)], max_rows=40)
        rep.p("Missing nutrients above must stay 'not available' in the app (never 0).")
        varying = df.groupby(food_col)[nutrient_cols].nunique(dropna=False).gt(1).sum().sum()
        rep.p(f"Nutrient values that differ between rows of the same food: **{int(varying)}** (0 means each food has one reference record).")
        first = df.groupby(food_col)[nutrient_cols].first()
        needed = {"energy_kcal", "protein_g", "carbohydrate_g", "fat_g"}
        if needed <= set(first.columns):
            at = 4 * first.protein_g + 4 * first.carbohydrate_g + 9 * first.fat_g
            diff = ((first.energy_kcal - at) / at.replace(0, np.nan) * 100).round(1)
            bad = diff[diff.abs() > 20]
            rep.p(f"Energy vs Atwater estimate (4P+4C+9F): foods differing by more than 20%: {', '.join(f'{k} ({v}%)' for k, v in bad.items()) or 'none'}.")
        rep.p("Nutrient basis is NOT stored in the CSV. The values must be documented as per 100 g (USDA reference) in the API.")
        rep.summary["nutrient_columns"] = nutrient_cols

    # ---- ids, paths, names
    rep.h("2.6 Identifiers, paths and filenames", 3)
    if "image_id" in df:
        rep.p(f"Duplicate image_id values: **{int(df['image_id'].duplicated().sum())}**.")
    if "image_path" in df:
        paths = df["image_path"].astype("string")
        dup_paths = int(paths.duplicated().sum())
        rep.p(f"Duplicate image_path values: **{dup_paths}**.")
        if dup_paths:
            rep.finding("HIGH", f"{dup_paths} duplicate image_path rows.")
        roots = paths.str.replace("\\", "/", regex=False).str.split("/").str[:3].str.join("/")
        rep.p("Where the CSV expects the images to be (first path components):")
        rep.table(roots.value_counts().rename_axis("path_prefix").reset_index(name="rows"))
        ext = paths.str.extract(r"(\.[A-Za-z0-9]+)$")[0].str.lower().value_counts(dropna=False)
        rep.p("File extensions: " + ", ".join(f"{k}={v:,}" for k, v in ext.items()))
    if "image_name" in df and "image_path" in df:
        dn = df[df["image_name"].duplicated(keep=False)]
        rep.p(f"Rows sharing an image_name with another row: {len(dn):,} (informational: same filename in different folders is not a duplicate "
              "image; never use the filename alone as an identifier).")

    # ---- augmentation families
    rep.h("2.7 Pre-augmented copies and split leakage (filename-based)", 3)
    if "image_name" in df and split_col:
        aug = df["image_name"].astype("string").str.extract(f"({AUG_RE.pattern})", flags=re.IGNORECASE)[0]
        base = df["image_name"].astype("string").str.replace(AUG_RE.pattern, "", regex=True, flags=re.IGNORECASE)
        src = df["source_dataset"].astype("string") if "source_dataset" in df else pd.Series("", index=df.index, dtype="string")
        cl = df["class"].astype("string") if "class" in df else pd.Series("", index=df.index, dtype="string")
        fd = df["food"].astype("string") if "food" in df else pd.Series("", index=df.index, dtype="string")
        df["family_key"] = src + "|" + fd + "|" + cl + "|" + base  # food is part of the key: 'fresh/1.jpg' exists for many foods
        n_aug = int(aug.notna().sum())
        rep.p(f"Filenames starting with an augmentation prefix ({AUG_RE.pattern}): **{n_aug:,}**.")
        if n_aug:
            rep.table(aug.value_counts().rename_axis("prefix").reset_index(name="rows"))
        fam = df.groupby("family_key").agg(n=("_split", "size"), ns=("_split", "nunique"))
        multi = fam[fam.n > 1]
        cross = multi[multi.ns > 1]
        rep.p(f"Families (original + its augmented copies) with more than one file: **{len(multi):,}**. "
              f"Families whose files sit in DIFFERENT splits: **{len(cross):,}** "
              f"({int(cross.n.sum()):,} images).")
        test_leak = df[(df["_split"] == "test") & df["family_key"].isin(cross.index)]
        sp_by_fam = df.groupby("family_key")["_split"].agg(set)
        test_twins = int(test_leak["family_key"].map(lambda k: bool(sp_by_fam[k] - {"test"})).sum()) if len(test_leak) else 0
        rep.p(f"Test images that have a train/validation 'twin' from the same family: **{test_twins:,}** "
              f"({test_twins / max((df['_split'] == 'test').sum(), 1) * 100:.1f}% of the test set).")
        rep.summary["family_leakage"] = {"families_multi": int(len(multi)), "families_cross_split": int(len(cross)),
                                         "images_in_cross_split_families": int(cross.n.sum()),
                                         "test_images_with_twin": test_twins}
        if test_twins:
            rep.finding("HIGH", f"Split leakage: {test_twins:,} test images ({test_twins / max((df['_split'] == 'test').sum(), 1) * 100:.1f}%) "
                                "have an augmented/original twin in train or validation (matched by filename family). "
                                "Test accuracy on this split would be inflated. Phase 3 will build a group-aware split "
                                "(your original CSV is left untouched).")
    # ---- image scan
    audit_images(df, args, rep)


def audit_images(df: pd.DataFrame, args, rep: Report) -> None:
    rep.h("2.8 Image files: existence, decoding, exact and near duplicates", 3)
    if "image_path" not in df:
        rep.p("No image_path column; skipped.")
        return
    if args.image_scan == "skip":
        rep.p("Image scan was SKIPPED (--image-scan skip). Existence, corruption and duplicate checks were not run.")
        rep.finding("INFO", "Image scan skipped: file existence, corruption and content-duplicate checks are NOT done yet.")
        return
    paths = df["image_path"].astype(str)
    if args.remap_from and args.remap_to:
        lo = args.remap_from.lower()
        paths = paths.map(lambda p: args.remap_to + p[len(args.remap_from):] if p.lower().startswith(lo) else p)
        rep.p(f"Path remap applied: `{args.remap_from}` -> `{args.remap_to}`")
    idx = df.index
    sampled = False
    if args.limit and args.limit < len(df):
        rng = np.random.default_rng(args.seed)
        idx = df.index[np.sort(rng.choice(len(df), size=args.limit, replace=False))]
        sampled = True
        rep.p(f"**SAMPLED SCAN: {len(idx):,} of {len(df):,} images (seed {args.seed}).** Duplicate and leakage numbers below are lower bounds.")
        rep.finding("INFO", f"Image scan was a sample ({len(idx):,}/{len(df):,}); run without --limit for the full audit.")
    cache = REPORTS_DIR / "image_scan.csv"
    scan = None
    if args.reuse_scan and cache.is_file() and not sampled:
        old = pd.read_csv(cache, dtype={"dhash": str, "sha256": str})
        if len(old) == len(df) and set(old["image_id"].astype(str)) == set(df["image_id"].astype(str)):
            scan = old.set_index(old["image_id"].astype(str)).loc[df["image_id"].astype(str)].reset_index(drop=True)
            scan.index = df.index
            rep.p("Reused previous image scan from reports/image_scan.csv (--reuse-scan).")
    if scan is None:
        print(f"Scanning {len(idx):,} images with {args.workers} worker threads ...", flush=True)
        res = run_scan(paths.loc[idx].tolist(), args.workers)
        scan = pd.DataFrame(res, index=idx)
        scan.insert(0, "image_id", df.loc[idx, "image_id"].astype(str).values if "image_id" in df else idx)
        if not sampled:
            scan.to_csv(cache, index=False)
    scan["dhash"] = scan["dhash"].fillna("").astype(str)
    scan["sha256"] = scan["sha256"].fillna("").astype(str)
    n = len(scan)
    exists = scan["exists"].astype(bool)
    ok = scan["decode_ok"].astype(bool)
    rep.p(f"Scanned **{n:,}** images: found **{int(exists.sum()):,}**, missing **{int((~exists).sum()):,}**, "
          f"exist but cannot be decoded **{int((exists & ~ok).sum()):,}**, valid **{int(ok.sum()):,}**.")
    if (~exists).any():
        rep.finding("HIGH", f"{int((~exists).sum()):,} of {n:,} scanned image paths do not exist. "
                            "If you moved the image folder, use --remap-from/--remap-to.")
        first_missing = df.loc[scan.index[~exists], "image_path"].astype(str).head(3).tolist()
        rep.p("Examples of missing paths: " + "; ".join(f"`{x}`" for x in first_missing))
    if (exists & ~ok).any():
        rep.finding("HIGH", f"{int((exists & ~ok).sum())} image files exist but are corrupt/unreadable.")
        rep.table(scan.loc[exists & ~ok, ["image_id", "error"]].head(20))
    v = scan[ok]
    if len(v):
        rep.p("Image size/format statistics (valid images):")
        stats = pd.DataFrame({
            "stat": ["width min / median / max", "height min / median / max", "file KB min / median / max",
                     "images smaller than 64px (either side)"],
            "value": [f"{int(v.width.min())} / {int(v.width.median())} / {int(v.width.max())}",
                      f"{int(v.height.min())} / {int(v.height.median())} / {int(v.height.max())}",
                      f"{v.bytes.min()/1024:.0f} / {v.bytes.median()/1024:.0f} / {v.bytes.max()/1024:.0f}",
                      int(((v.width < 64) | (v.height < 64)).sum())]})
        rep.table(stats)
        rep.p("Formats: " + ", ".join(f"{k}={c:,}" for k, c in v["format"].value_counts().items())
              + " | Modes: " + ", ".join(f"{k}={c:,}" for k, c in v["mode"].value_counts().items()))
    # ---- duplicates
    work = pd.DataFrame({"split": df.loc[scan.index, "_split"].astype(str).values,
                         "food": df.loc[scan.index, "food"].astype(str).values if "food" in df else "",
                         "sha256": scan["sha256"].values, "dhash": scan["dhash"].values}, index=scan.index)
    work = work[ok.values]
    ex = work[work.sha256 != ""].copy()
    ex["exact_group"] = ex.groupby("sha256").ngroup()
    sizes = ex.groupby("exact_group").size()
    ex.loc[ex.exact_group.map(sizes) < 2, "exact_group"] = -1
    exact = group_leakage(ex, "exact_group", "split", "food")
    rep.h("Exact duplicates (identical file bytes)", 4)
    rep.table(pd.DataFrame([exact]))
    if exact["groups_cross_split"]:
        rep.finding("HIGH", f"{exact['groups_cross_split']} groups of byte-identical images appear in more than one split "
                            f"({exact['images_in_cross_split_groups']} images).")
    if exact["groups_cross_label"]:
        rep.finding("HIGH", f"{exact['groups_cross_label']} groups of identical images carry DIFFERENT food labels (label noise).")
    work["exact_group"] = -1
    work.loc[ex.index, "exact_group"] = ex["exact_group"]
    near_g, skipped = near_duplicate_groups(work["dhash"], args.near_dup_distance, args.bucket_cap)
    work["near_group"] = near_g
    near = group_leakage(work, "near_group", "split", "food")
    rep.h(f"Near duplicates (perceptual hash distance <= {args.near_dup_distance} of 64 bits)", 4)
    rep.table(pd.DataFrame([near]))
    rep.p("Perceptual hashing catches resized / re-compressed / lightly edited copies. It does NOT catch strongly rotated or shifted "
          "copies (see section 2.7 for those) and may flag genuinely similar photos; treat these as candidates to review, not proof."
          + (f" {skipped} very large hash buckets were skipped (usually blank/flat images)." if skipped else ""))
    if near["groups_cross_split"]:
        rep.finding("HIGH" if near["test_images_with_train_or_val_twin"] > 0 else "MEDIUM",
                    f"{near['groups_cross_split']} near-duplicate groups span splits; {near['test_images_with_train_or_val_twin']} test images "
                    "have a near-duplicate in train/validation.")
    rep.summary["images"] = {"scanned": n, "sampled": sampled, "missing": int((~exists).sum()),
                             "corrupt": int((exists & ~ok).sum()), "exact": exact, "near": near}
    out = pd.DataFrame({"image_id": df.loc[work.index, "image_id"].values if "image_id" in df else work.index,
                        "split": work["split"].values,
                        "family_key": df.loc[work.index, "family_key"].values if "family_key" in df else "",
                        "exact_group": work["exact_group"].values, "near_group": work["near_group"].values})
    flagged = out[(out.exact_group >= 0) | (out.near_group >= 0)]
    flagged.to_csv(REPORTS_DIR / "image_groups.csv", index=False)
    bad = scan[(~exists) | (exists & ~ok)][["image_id", "exists", "error"]]
    bad.to_csv(REPORTS_DIR / "flagged_images.csv", index=False)


# ----------------------------------------------------------------------------- packaged foods
def audit_packaged(df: pd.DataFrame, rep: Report) -> None:
    rep.h("3. Packaged food nutrition table (packaged_foods_india_clean.csv)")
    rep.p(f"Rows: **{len(df):,}**, columns: **{df.shape[1]}**.")
    rep.table(schema_table(df), max_rows=40)
    c = {k: pick(df, *a) for k, a in {
        "id": ("product_id",), "name": ("Item name", "item_name"), "brand": ("Brand_Name",), "serving": ("Serving_Size_g",),
        "kcal": ("Calories_kcal",), "carb": ("Carbohydrates_g",), "prot": ("Proteins_g",), "fat": ("Total_Fat_g",),
        "sat": ("Saturated_Fat_g",), "sugar": ("Sugar_g",), "sodium": ("Sodium_mg",), "fiber": ("Dietary_Fiber_g",),
        "ingr": ("Ingredients",), "source": ("Source_of_Data",), "date": ("Collection_Date",), "by": ("Collected_By",)}.items()}
    if c["id"]:
        rep.p(f"Duplicate product_id: **{int(df[c['id']].duplicated().sum())}**.")
    flags: list[dict] = []

    def flag(mask: pd.Series, reason: str) -> None:
        for i in df.index[mask.fillna(False)]:
            flags.append({"row": int(i), "product_id": df.at[i, c["id"]] if c["id"] else i,
                          "item": df.at[i, c["name"]] if c["name"] else "", "reason": reason})

    nutr = [df[x].name for x in (c["kcal"], c["carb"], c["prot"], c["fat"], c["sat"], c["sugar"], c["sodium"], c["fiber"]) if x]
    rep.h("3.1 Zero values that may really be 'not listed'", 3)
    z = pd.DataFrame({"column": [x for x in df.columns if x.endswith(("_g", "_mg"))],
                      "rows_equal_0_%": [round((df[x] == 0).mean() * 100, 1) for x in df.columns if x.endswith(("_g", "_mg"))],
                      "missing_%": [round(df[x].isna().mean() * 100, 1) for x in df.columns if x.endswith(("_g", "_mg"))]})
    rep.table(z, max_rows=30)
    cal, iron = pick(df, "Calcium_mg"), pick(df, "Iron_mg")
    if cal and iron:
        both0 = ((df[cal] == 0) & (df[iron] == 0)).mean() * 100
        rep.p(f"Rows where calcium AND iron are both exactly 0: **{both0:.1f}%**. Real foods rarely have both at exactly zero, so these zeros "
              "most likely mean 'not on the label'. They must be treated as missing, not zero.")
        if both0 > 30:
            rep.finding("HIGH", f"{both0:.0f}% of packaged products have calcium=0 and iron=0 - almost certainly missing values stored as 0. "
                                "Convert to 'not available' before showing them.")
    vit = pick(df, "Vitamin")
    if vit:
        rep.p(f"`{vit}` is free text; value '0' appears in {int((df[vit].astype(str) == '0').sum())} rows (again, '0' means 'not listed').")
    rep.h("3.2 Serving basis", 3)
    if c["serving"]:
        s = df[c["serving"]]
        rep.p(f"Serving_Size_g equals 100 in **{int((s == 100).sum())}** rows and differs in **{int((s != 100).sum())}** rows. "
              "There is NO column that says whether nutrient values are per 100 g or per serving, so the basis of those rows is ambiguous.")
        if (s != 100).sum():
            rep.finding("HIGH", f"{int((s != 100).sum())} packaged rows have a serving size other than 100 g and the table has no basis column "
                                "(per 100 g vs per serving). Per-serving and per-100 g values must never be mixed.")
    rep.h("3.3 Impossible or suspicious values", 3)
    if all(c[k] for k in ("serving", "kcal", "carb", "prot", "fat")):
        cap = df[c["serving"]].clip(lower=100)
        for key, label in (("carb", "carbohydrates"), ("prot", "protein"), ("fat", "fat"), ("fiber", "fiber"), ("sugar", "sugar")):
            if c[key]:
                flag(df[c[key]] > cap * 1.02, f"{label} exceeds {label} possible in {{serving}} g (impossible)")
        flag((df[c["carb"]] + df[c["prot"]] + df[c["fat"]]) > cap * 1.05, "carbs+protein+fat exceed the food's weight")
        flag(df[c["kcal"]] > 9.5 * cap, "energy above 9.5 kcal per gram (impossible)")
        flag(df[c["kcal"]] == 0, "0 kcal listed (check: water-like drink or missing?)")
        if c["sugar"]:
            flag(df[c["sugar"]] > df[c["carb"]] * 1.05 + 0.5, "sugar greater than total carbohydrate")
        if c["sat"]:
            flag(df[c["sat"]] > df[c["fat"]] + 0.5, "saturated fat greater than total fat")
        if c["fiber"]:
            flag(df[c["fiber"]] > df[c["carb"]] + 0.5, "fiber greater than total carbohydrate")
        if c["sodium"]:
            flag(df[c["sodium"]] > 10000, "sodium above 10,000 mg (verify: seasoning/pickle or typo)")
        atw = 4 * df[c["prot"]] + 4 * df[c["carb"]] + 9 * df[c["fat"]]
        flag(((df[c["kcal"]] - atw).abs() / atw.replace(0, np.nan)) > 0.35, "energy differs >35% from 4P+4C+9F estimate (verify)")
    fl = pd.DataFrame(flags)
    if len(fl):
        fl["reason"] = fl["reason"].str.replace("{serving}", "its", regex=False)
        fl.to_csv(REPORTS_DIR / "packaged_food_flags.csv", index=False)
        summ = fl.groupby("reason").size().rename("rows").reset_index().sort_values("rows", ascending=False)
        rep.table(summ, max_rows=20)
        rep.p(f"{fl['row'].nunique()} distinct rows flagged (full list: reports/packaged_food_flags.csv).")
        rep.finding("MEDIUM", f"{fl['row'].nunique()} packaged rows have impossible/suspicious nutrient values (see packaged_food_flags.csv).")
    rep.h("3.4 Duplicates and provenance", 3)
    if c["name"] and c["brand"]:
        d = df[df.duplicated([c["name"], c["brand"]], keep=False)]
        rep.p(f"Rows sharing the same name+brand with another row: **{len(d)}**; exact full-row duplicates (ignoring ids): "
              f"**{int(df.drop(columns=[x for x in (c['id'], pick(df, 'S.No')) if x]).duplicated().sum())}**.")
    prov = {k: int(df[c[k]].notna().sum()) for k in ("source", "date", "by") if c[k]}
    rep.p("Provenance fields filled in (of %d rows): %s" % (len(df), prov))
    if prov and max(prov.values()) < len(df) * 0.1:
        rep.finding("MEDIUM", "Almost no provenance recorded (source/date/collector). You cannot trace where nutrient values came from, "
                              "and the sources that are named may have terms-of-use limits.")
    rep.p("This table has no product images or barcodes, so it cannot be used to train or test OCR.")


# ----------------------------------------------------------------------------- additives
INS_TEXT_RE = re.compile(r"(?:\bINS\b|\bE)\s*[-:.]?\s*(\d{3,4})", re.IGNORECASE)
INS_KW_RE = re.compile(r"(?:agents?|emulsifiers?|colou?rs?|preservatives?|regulators?|antioxidants?|stabili[sz]ers?|thickeners?|"
                       r"humectants?|conditioners?|enhancers?)\s*[\[\(:]?\s*(?:INS\s*)?(\d{3,4})\b", re.IGNORECASE)


def ins_digits(s: object) -> str | None:
    m = re.search(r"(\d{3,4})", str(s))
    return m.group(1) if m else None


def ins_format_issue(code: str) -> str | None:
    if len(code) == 4:
        n = int(code)
        if code[0] != "1":
            return "4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code)"
        if not (1100 <= n <= 1105 or 1200 <= n <= 1203 or 1400 <= n <= 1452 or 1501 <= n <= 1521):
            return "4-digit code outside the common INS blocks - verify manually"
    return None


def audit_additives(add: pd.DataFrame, ref: pd.DataFrame | None, pack: pd.DataFrame | None, rep: Report) -> None:
    rep.h("4. Additive occurrences (packaged_food_additives.csv)")
    rep.p(f"Rows: **{len(add):,}**, columns: **{add.shape[1]}**.")
    rep.table(schema_table(add))
    expected = ["product_id", "item_name", "brand", "category", "ingredient_text", "ins_code_exact", "ins_code_base"]
    miss = [x for x in expected if x not in add.columns]
    if miss:
        rep.finding("HIGH", f"Additive occurrence table is missing columns {miss}.")
        return
    rep.p(f"Distinct products: **{add.product_id.nunique()}**, distinct base INS codes: **{add.ins_code_base.nunique()}**, "
          f"distinct exact codes: **{add.ins_code_exact.nunique()}**. Duplicate (product, exact code) rows: "
          f"**{int(add.duplicated(['product_id', 'ins_code_exact']).sum())}**.")
    rep.p("This file lists WHICH additives each product contains. It has no function/regulatory columns; explanations come from the "
          "reference table (section 5).")
    base_digits = add.ins_code_base.map(ins_digits)
    issues = pd.DataFrame({"code": add.ins_code_base, "digits": base_digits})
    issues["issue"] = issues.digits.map(lambda d: ins_format_issue(d) if d else "no digits found")
    bad = issues[issues.issue.notna()].groupby(["code", "issue"]).size().rename("rows").reset_index()
    rep.h("4.1 Code format screen (not a verification against Codex)", 3)
    rep.table(bad)
    if len(bad):
        rep.finding("HIGH", f"{len(bad)} additive codes look malformed or unverifiable: {', '.join(bad.code.tolist())}. "
                            "Check them against the original ingredient text and the Codex INS list.")
    if pack is not None:
        idc, ingc = pick(pack, "product_id"), pick(pack, "Ingredients")
        rep.h("4.2 Consistency with the packaged-food table", 3)
        orphan = int((~add.product_id.isin(pack[idc])).sum())
        m = add.merge(pack[[idc, ingc]], left_on="product_id", right_on=idc, how="left", suffixes=("", "_pack"))
        mism = int((m["ingredient_text"] != m[ingc]).sum())
        rep.p(f"Additive rows whose product_id is not in the packaged table: **{orphan}**; ingredient text differs from the packaged table: **{mism}**.")
        rep.h("4.3 Additives written in the ingredient text but missing from this table", 3)
        have = add.groupby("product_id")["ins_code_base"].apply(lambda s: {ins_digits(x) for x in s})
        rows = []
        for _, r in pack.iterrows():
            txt = str(r[ingc])
            t1 = set(INS_TEXT_RE.findall(txt))
            t2 = set(INS_KW_RE.findall(txt)) - t1
            known = have.get(r[idc], set())
            miss1, miss2 = t1 - known, t2 - known
            if miss1 or miss2:
                rows.append({"product_id": r[idc], "missing_INS_or_E_codes": ", ".join(sorted(miss1)),
                             "missing_keyword_codes": ", ".join(sorted(miss2))})
        mdf = pd.DataFrame(rows)
        n1 = int((mdf["missing_INS_or_E_codes"] != "").sum()) if len(mdf) else 0
        n2 = int((mdf["missing_keyword_codes"] != "").sum()) if len(mdf) else 0
        rep.p(f"Products with an `INS ###` / `E###` code in the text that is NOT in the additive table: **{n1}**. "
              f"Products with extra codes written like 'EMULSIFIER [472e]': **{n2}**. (Regex screen; review before trusting.)")
        if len(mdf):
            mdf.to_csv(REPORTS_DIR / "additive_extraction_gaps.csv", index=False)
            allc = Counter(c for s in mdf["missing_INS_or_E_codes"] for c in s.split(", ") if c)
            rep.p("Most common missed codes: " + ", ".join(f"{k} x{v}" for k, v in allc.most_common(12)))
            rep.table(mdf.head(10))
        if n1 or n2:
            rep.finding("HIGH", f"Additive extraction is incomplete: {n1} products have INS/E codes in the text that the table misses "
                                f"(+{n2} with codes written like 'EMULSIFIER [472e]' or 'RAISING AGENTS 503'; {len(mdf)} products in total have at least one missed code). "
                            "The extractor probably needs the word 'INS' and ignores the 'E' prefix and bare numbers after a function name. "
                                "Full list: reports/additive_extraction_gaps.csv.")
        rep.p(f"Products with at least one extracted additive: {add.product_id.nunique()} of {len(pack)} "
              f"({add.product_id.nunique() / len(pack) * 100:.0f}%).")


def audit_additive_ref(ref: pd.DataFrame, add: pd.DataFrame | None, rep: Report) -> None:
    rep.h("5. Additive reference table (additive_reference_populated.csv)")
    rep.p(f"Rows: **{len(ref):,}**, columns: **{ref.shape[1]}**.")
    rep.table(schema_table(ref))
    exp = ["ins_code", "additive_name", "functional_class", "jecfa_status", "codex_status", "safety_note", "source"]
    miss = [x for x in exp if x not in ref.columns]
    if miss:
        rep.finding("HIGH", f"Additive reference is missing columns {miss}.")
        return
    rep.p(f"Duplicate ins_code values: **{int(ref.ins_code.duplicated().sum())}**.")
    digits = ref.ins_code.map(ins_digits)
    fmt = pd.DataFrame({"ins_code": ref.ins_code, "name": ref.additive_name,
                        "issue": digits.map(lambda d: ins_format_issue(d) if d else "no digits")})
    fmt = fmt[fmt.issue.notna()]
    rep.h("5.1 Format screen of reference codes", 3)
    rep.table(fmt)
    if len(fmt):
        rep.finding("HIGH", f"{len(fmt)} reference entries have codes that look malformed ({', '.join(fmt.ins_code)}) yet carry specific "
                            "additive names. Names for such codes may be wrong; verify each against Codex.")
    rep.h("5.2 How informative are the regulatory fields?", 3)
    vague = ref[~ref.jecfa_status.astype(str).str.contains(r"ADI\b|\d", regex=True)]
    rep.p(f"`jecfa_status` entries without any ADI figure or explicit 'ADI not specified/no ADI': **{len(vague)}** "
          f"(values: {', '.join(sorted(vague.jecfa_status.astype(str).unique())[:8])}).")
    rep.p(f"`safety_note` distinct values: **{ref.safety_note.nunique()}** of {len(ref)}; most repeated: "
          f"{ref.safety_note.value_counts().head(3).to_dict()}.")
    has_url = ref.source.astype(str).str.contains("http|doi|STAN|JECFA monograph", case=False, regex=True).sum()
    rep.p(f"`source` values naming a specific document/URL: **{int(has_url)}** of {len(ref)} (values seen: {ref.source.value_counts().to_dict()}).")
    rep.finding("MEDIUM", "The additive reference cites organisations (Codex/JECFA/FSSAI) but no specific document, version or URL per entry, "
                          "so none of its regulatory statements can be traced. Treat as UNVERIFIED until checked against the primary sources.")
    if add is not None and "ins_code_base" in add:
        used = set(add.ins_code_base.astype(str).str.strip().str.upper())
        have = set(ref.ins_code.astype(str).str.strip().str.upper())
        rep.h("5.3 Coverage", 3)
        rep.p(f"Codes used by products but missing from the reference: **{len(used - have)}**. Reference codes never used by any product: "
              f"**{len(have - used)}**.")
        if not (have - used):
            rep.finding("MEDIUM", "Every reference code occurs in your 852 products and nothing else: the reference appears to be built only from "
                                  "observed codes. Any other INS code the OCR finds will have no entry (the app must say 'not in our reference').")
    rep.p("This script can only screen format and consistency. It cannot verify the regulatory content itself.")


# ----------------------------------------------------------------------------- OCR dataset inventory
def audit_ocr_dir(ocr_dir: Path, rep: Report) -> None:
    rep.h("6. OCR dataset inventory (--ocr-dir)")
    if not ocr_dir.is_dir():
        rep.p(f"`{ocr_dir}` is not a folder.")
        rep.finding("HIGH", f"--ocr-dir {ocr_dir} not found.")
        return
    ext = Counter()
    top = Counter()
    label_files: list[Path] = []
    images = 0
    for dp, dn, fn in os.walk(ocr_dir):
        rel = Path(dp).relative_to(ocr_dir)
        key = rel.parts[0] if rel.parts else "(root)"
        for f in fn:
            e = Path(f).suffix.lower()
            ext[e] += 1
            top[key] += 1
            if e in IMAGE_EXTS:
                images += 1
            elif e in {".txt", ".json", ".csv", ".tsv", ".xml", ".jsonl"} and len(label_files) < 25:
                label_files.append(Path(dp) / f)
    rep.p(f"Total files: **{sum(ext.values()):,}**, image files: **{images:,}**.")
    rep.table(pd.DataFrame(ext.most_common(), columns=["extension", "files"]))
    rep.table(pd.DataFrame(top.most_common(15), columns=["top-level folder", "files"]))
    rep.p("Label/annotation file candidates (first lines shown so we learn the real format before building anything):")
    for lf in label_files[:6]:
        try:
            with open(lf, "r", encoding="utf-8", errors="replace") as fh:
                head = [line.rstrip()[:160] for line in islice(fh, 3)] or ["(empty file)"]
        except OSError as exc:
            head = [f"(unreadable: {exc})"]
        rep.p(f"`{lf.relative_to(ocr_dir)}`:\n```\n" + "\n".join(head) + "\n```")
    rep.summary["ocr"] = {"files": sum(ext.values()), "images": images}


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="SmartPlateAI dataset audit (read-only).")
    ap.add_argument("--extra-root", action="append", help="Extra folder to search for the CSVs (repeatable).")
    ap.add_argument("--max-depth", type=int, default=4, help="Folder levels to search below each root.")
    ap.add_argument("--food-csv"); ap.add_argument("--packaged-csv")
    ap.add_argument("--additives-csv"); ap.add_argument("--additive-ref-csv")
    ap.add_argument("--ocr-dir", help="Optional: folder of the OCR dataset to inventory.")
    ap.add_argument("--image-scan", choices=["full", "skip"], default="full")
    ap.add_argument("--limit", type=int, default=0, help="Scan only a random sample of N images (quick test).")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--reuse-scan", action="store_true", help="Reuse reports/image_scan.csv if present.")
    ap.add_argument("--remap-from"); ap.add_argument("--remap-to")
    ap.add_argument("--near-dup-distance", type=int, choices=[0, 1, 2, 3], default=2)
    ap.add_argument("--bucket-cap", type=int, default=3000)
    ap.add_argument("--min-class-images", type=int, default=500)
    args = ap.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    rep = Report()
    paths = resolve_paths(args, rep)
    data: dict[str, pd.DataFrame | None] = {}
    for k, p in paths.items():
        data[k] = load_csv(p) if p else None
        if p:
            print(f"Loaded {p.name}: {len(data[k]):,} rows x {data[k].shape[1]} cols")
    if data["food_csv"] is not None:
        audit_food(data["food_csv"], args, rep)
    if data["packaged_csv"] is not None:
        audit_packaged(data["packaged_csv"], rep)
    else:
        rep.finding("MEDIUM", "packaged_foods_india_clean.csv not found - packaged table not audited.")
    if data["additives_csv"] is not None:
        audit_additives(data["additives_csv"], data["additive_ref_csv"], data["packaged_csv"], rep)
    else:
        rep.finding("MEDIUM", "packaged_food_additives.csv not found - additive occurrences not audited.")
    if data["additive_ref_csv"] is not None:
        audit_additive_ref(data["additive_ref_csv"], data["additives_csv"], rep)
    if args.ocr_dir:
        audit_ocr_dir(Path(args.ocr_dir), rep)
    else:
        rep.h("6. OCR dataset inventory")
        rep.p("Not run. Pass --ocr-dir <folder> to inventory the OCR dataset. Its 21,840-image count is unverified until then.")
        rep.finding("INFO", "OCR dataset not inspected (no --ocr-dir given); its reported 21,840 images are unverified.")

    meta = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "version": "1.0"}
    (REPORTS_DIR / "dataset_audit_report.md").write_text(rep.render(meta), encoding="utf-8")
    rep.summary["paths"] = {k: str(v) if v else None for k, v in paths.items()}
    rep.summary["findings"] = [{"severity": s, "text": t} for s, t in rep.findings]
    (REPORTS_DIR / "dataset_audit.json").write_text(json.dumps(jsonable(rep.summary), indent=2), encoding="utf-8")
    (REPORTS_DIR / "dataset_paths.json").write_text(json.dumps(
        {k: str(v) if v else None for k, v in paths.items()}, indent=2), encoding="utf-8")

    print("\n================ AUDIT SUMMARY ================")
    for sev, txt in sorted(rep.findings, key=lambda x: {"HIGH": 0, "MEDIUM": 1, "INFO": 2}.get(x[0], 9)):
        print(f"[{sev}] {txt}")
    print(f"\nReports written to: {REPORTS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())