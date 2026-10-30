"""
SmartPlateAI - Phase 3: group-aware train/validation/test split (NO training, READ-ONLY on source data).

Inputs  (written by Phase 1):  reports\\dataset_paths.json, reports\\image_scan.csv
Outputs: data_prep\\split_manifest.csv, data_prep\\excluded_samples.csv, data_prep\\split_config.json,
         reports\\phase3\\*

Image groups = connected components of three relations (any one links two images):
  1. same augmentation family (filename prefix rule, e.g. rotated_by_15_<name>)
  2. byte-identical files (SHA-256)
  3. perceptually near-identical (64-bit dHash, Hamming distance <= --near-dup-distance)
Whole groups are assigned to ONE split, so no group can cross train/validation/test.

Usage:  python scripts\\prepare_splits.py            (build + validate)
        python scripts\\prepare_splits.py --validate-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_VERSION = "3.0"
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = BACKEND_DIR / "reports"
OUT_REPORTS = REPORTS_DIR / "phase3"
DATA_PREP = BACKEND_DIR / "data_prep"
SPLITS = ("train", "val", "test")

BAD_TOKENS = {"", "nan", "none", "null", "unknown", "other", "unlabeled", "unlabelled", "?", "n/a", "na"}
SPLIT_ALIASES = {"train": "train", "training": "train", "valid": "val", "validation": "val",
                 "val": "val", "test": "test", "testing": "test"}
AUG_RE = re.compile(r"^(?:rotated_by_\d+|translation|flipped|flip|zoom|shear)_", re.IGNORECASE)

# Documented, verifiable freshness rule R1 (FruitQuality1 only): the label is the name of the source
# folder that contains the image, and it must agree with the CSV `class` and `food` columns.
FQ1_FOLDER_RULE = {
    "freshapples": ("Apple", "Fresh"), "rottenapples": ("Apple", "Rotten"),
    "freshbanana": ("Banana", "Fresh"), "rottenbanana": ("Banana", "Rotten"),
    "freshoranges": ("Orange", "Fresh"), "rottenoranges": ("Orange", "Rotten"),
}


# ----------------------------------------------------------------------------- helpers
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Could not decode {path}")


def md_table(df: pd.DataFrame, max_rows: int = 60) -> str:
    if df is None or len(df) == 0:
        return "_(none)_\n"
    d = df.head(max_rows).copy().astype(object)
    d = d.where(d.notna(), "")
    cols = [str(c) for c in d.columns]
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, r in d.iterrows():
        out.append("| " + " | ".join(str(v).replace("|", "\\|") for v in r) + " |")
    if len(df) > max_rows:
        out.append(f"\n_... {len(df) - max_rows} more rows not shown._")
    return "\n".join(out) + "\n"


def make_family_key(df: pd.DataFrame) -> pd.Series:
    base = df["image_name"].astype("string").str.replace(AUG_RE.pattern, "", regex=True, flags=re.IGNORECASE)
    return (df["source_dataset"].astype("string") + "|" + df["food"].astype("string") + "|"
            + df["class"].astype("string") + "|" + base)


class DSU:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.size = [1] * n

    def find(self, x: int) -> int:
        p = self.parent
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a: int, b: int, cap: int | None = None) -> str:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return "same"
        if cap is not None and self.size[ra] + self.size[rb] > cap:
            return "capped"
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]
        return "merged"


def popcount64(x: np.ndarray) -> np.ndarray:
    x = x - ((x >> np.uint64(1)) & np.uint64(0x5555555555555555))
    x = (x & np.uint64(0x3333333333333333)) + ((x >> np.uint64(2)) & np.uint64(0x3333333333333333))
    x = (x + (x >> np.uint64(4))) & np.uint64(0x0F0F0F0F0F0F0F0F)
    return (x * np.uint64(0x0101010101010101)) >> np.uint64(56)


def iter_near_pairs(vals: np.ndarray, dist: int):
    """Yield every index pair (i, j) whose 64-bit hashes differ in exactly `dist` bits (dist <= 3).
    Exact and complete: two hashes within 3 bits must agree on at least one of four 16-bit chunks
    (pigeonhole), so comparing all pairs inside equal-chunk buckets misses nothing. No bucket is skipped."""
    with np.errstate(over="ignore"):
        for chunk in range(4):
            keys = (vals >> np.uint64(16 * chunk)) & np.uint64(0xFFFF)
            order = np.argsort(keys, kind="stable")
            bounds = np.flatnonzero(np.diff(keys[order])) + 1
            for members in np.split(order, bounds):
                m = len(members)
                if m < 2:
                    continue
                arr = vals[members]
                for i in range(m - 1):
                    d = popcount64(arr[i] ^ arr[i + 1:])
                    for j in np.flatnonzero(d == dist):
                        yield int(members[i]), int(members[i + 1 + j])


def hash_values(series: pd.Series) -> np.ndarray:
    return np.array([int(h, 16) for h in series.values], dtype=np.uint64)


# ----------------------------------------------------------------------------- freshness rule
def derive_freshness(df: pd.DataFrame, accept_rule: bool) -> pd.DataFrame:
    cond = df["condition"].astype("string").str.strip()
    orig = cond.where(cond.str.lower().isin(["fresh", "rotten"]), "Unknown").str.capitalize()
    orig = orig.where(orig.isin(["Fresh", "Rotten"]), "Unknown")
    cls = df["class"].astype("string").str.strip().str.lower()
    # original labels must not contradict an explicit fresh/rotten class
    cls_implied = pd.Series("", index=df.index, dtype="string")
    cls_implied[cls == "fresh"] = "Fresh"
    cls_implied[cls == "rotten"] = "Rotten"
    conflict = (orig != "Unknown") & (cls_implied != "") & (orig != cls_implied)
    # rule R1 candidates
    folder = df["image_path"].astype("string").str.replace("\\", "/", regex=False).str.split("/").str[-2].str.lower()
    cand = pd.Series("", index=df.index, dtype="string")
    for fname, (food, label) in FQ1_FOLDER_RULE.items():
        ok = ((df["source_dataset"] == "FruitQuality1") & (folder == fname) & (cls == fname) & (df["food"] == food))
        cand[ok] = label
    # candidates are only considered where the original label is missing
    cand = cand.where(orig == "Unknown", "")
    # all members of an augmentation family must agree
    fam = make_family_key(df)
    tmp = pd.DataFrame({"fam": fam, "cand": cand})
    nun = tmp[tmp.cand != ""].groupby("fam")["cand"].nunique()
    bad_fam = set(nun[nun > 1].index)
    cand = cand.where(~fam.isin(bad_fam), "")
    label = orig.copy()
    source = pd.Series("none", index=df.index, dtype="string")
    source[orig != "Unknown"] = "original_label"
    label[conflict] = "Unknown"
    source[conflict] = "conflict_with_class"
    if accept_rule:
        take = (label == "Unknown") & (cand != "")
        label[take] = cand[take]
        source[take] = "folder_rule_R1"
    out = pd.DataFrame({
        "condition_original": cond.fillna("Unknown"),
        "freshness_candidate": cand.replace("", pd.NA),
        "freshness_candidate_source": pd.Series(pd.NA, index=df.index, dtype="string").mask(cand != "", "folder_rule_R1"),
        "freshness_label": label, "freshness_label_source": source,
    })
    out["freshness_trainable"] = out["freshness_label"].isin(["Fresh", "Rotten"])
    out.attrs["conflicts"] = int(conflict.sum())
    out.attrs["family_conflicts"] = len(bad_fam)
    return out


# ----------------------------------------------------------------------------- group-aware stratified assignment
def assign_groups(inc: pd.DataFrame, ratios: tuple[float, float, float], seed: int) -> pd.Series:
    rng = random.Random(seed)
    gk = inc.groupby(["group_id", "strat_key"]).size()
    groups: dict[int, dict[str, int]] = {}
    for (gid, key), n in gk.items():
        groups.setdefault(int(gid), {})[str(key)] = int(n)
    order = sorted(groups)
    rng.shuffle(order)                                   # seeded tie-break
    order.sort(key=lambda g: -sum(groups[g].values()))   # largest groups first (stable)
    ratios_a = np.array(ratios, dtype=float)
    totals = inc["strat_key"].value_counts()
    target = {str(k): ratios_a * v for k, v in totals.items()}
    current = {k: np.zeros(3) for k in target}
    overall_t, overall_c = ratios_a * len(inc), np.zeros(3)
    assign: dict[int, int] = {}
    for g in order:
        score = np.zeros(3)
        for key, n in groups[g].items():
            score += n * (target[key] - current[key]) / np.maximum(target[key], 1e-9)
        score += 1e-6 * (overall_t - overall_c) / np.maximum(overall_t, 1e-9)
        k = int(np.argmax(score))
        assign[g] = k
        for key, n in groups[g].items():
            current[key][k] += n
        overall_c[k] += sum(groups[g].values())
    return inc["group_id"].map(lambda g: SPLITS[assign[int(g)]])


# ----------------------------------------------------------------------------- verification (independent of the builder)
def verify(man: pd.DataFrame, near_dist: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []

    def add(name: str, passed: bool, detail: str, hard: bool = True) -> None:
        rows.append({"check": name, "result": "PASS" if passed else ("FAIL" if hard else "REVIEW"),
                     "detail": detail, "type": "hard" if hard else "soft"})

    add("image_id unique", not man["image_id"].duplicated().any(), f"{int(man['image_id'].duplicated().sum())} duplicates")
    add("every image has a split in {train,val,test}", man["new_split"].isin(SPLITS).all(),
        f"{int((~man['new_split'].isin(SPLITS)).sum())} invalid")
    g = man.groupby("group_id")["new_split"].nunique()
    add("no group_id crosses splits", int((g > 1).sum()) == 0, f"{int((g > 1).sum())} groups cross splits of {len(g):,}")
    s = man[man.sha256.astype(str).str.len() > 0].groupby("sha256")["new_split"].nunique()
    add("no byte-identical image (SHA-256) crosses splits", int((s > 1).sum()) == 0, f"{int((s > 1).sum())} hashes cross splits")
    fam = make_family_key(man)
    f = pd.DataFrame({"fam": fam, "sp": man["new_split"]}).groupby("fam")["sp"].nunique()
    add("no augmentation family (recomputed from filenames) crosses splits", int((f > 1).sum()) == 0,
        f"{int((f > 1).sum())} families cross splits of {len(f):,}")
    vals = hash_values(man["dhash"])
    sp = man["new_split"].to_numpy()
    cross: dict[tuple[int, int], int] = {}
    total_pairs = 0
    for d in range(near_dist + 1):
        for i, j in iter_near_pairs(vals, d):
            total_pairs += 1
            if sp[i] != sp[j]:
                cross[(i, j)] = d
    add(f"near-duplicate pairs (dHash distance <= {near_dist}) crossing splits", len(cross) == 0,
        f"{len(cross):,} of {total_pairs:,} near-duplicate pairs cross splits", hard=False)
    pairs = pd.DataFrame([{"image_id_a": man["image_id"].iloc[i], "image_id_b": man["image_id"].iloc[j],
                           "split_a": sp[i], "split_b": sp[j], "hamming_distance": d,
                           "food_a": man["food"].iloc[i], "food_b": man["food"].iloc[j]}
                          for (i, j), d in list(cross.items())[:5000]])
    return pd.DataFrame(rows), pairs


# ----------------------------------------------------------------------------- build
def build(args) -> int:
    for d in (DATA_PREP, OUT_REPORTS):
        d.mkdir(parents=True, exist_ok=True)
    paths_file = REPORTS_DIR / "dataset_paths.json"
    scan_file = Path(args.scan) if args.scan else REPORTS_DIR / "image_scan.csv"
    if not scan_file.is_file():
        print(f"ERROR: {scan_file} not found. Re-run the Phase 1 audit WITHOUT --limit (full image scan).")
        return 1
    food_csv = Path(args.food_csv) if args.food_csv else None
    if food_csv is None:
        if not paths_file.is_file():
            print("ERROR: reports\\dataset_paths.json not found. Re-run the Phase 1 audit or pass --food-csv.")
            return 1
        food_csv = Path(json.loads(paths_file.read_text())["food_csv"] or "")
    if not food_csv.is_file():
        print(f"ERROR: food CSV not found: {food_csv}")
        return 1
    src_hash_before = sha256_file(food_csv)
    df = load_csv(food_csv)
    need = ["image_id", "image_name", "image_path", "food", "class", "condition", "source_dataset", "split"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        print(f"ERROR: food CSV is missing columns {miss}")
        return 1
    df["image_id"] = df["image_id"].astype(str)
    if df["image_id"].duplicated().any():
        print("ERROR: duplicate image_id values in the food CSV.")
        return 1
    scan = pd.read_csv(scan_file, dtype={"image_id": str, "dhash": str, "sha256": str}, low_memory=False)
    scan["dhash"] = scan["dhash"].fillna("")
    scan["sha256"] = scan["sha256"].fillna("")
    if len(scan) != len(df) or set(scan["image_id"]) != set(df["image_id"]):
        print(f"ERROR: image_scan.csv ({len(scan):,} rows) does not match the food CSV ({len(df):,} rows). "
              "Re-run the Phase 1 audit with a full scan (no --limit).")
        return 1
    df = df.merge(scan[["image_id", "exists", "decode_ok", "sha256", "dhash"]], on="image_id", how="left", validate="one_to_one")
    df["food"] = df["food"].astype("string").str.strip()
    df["class"] = df["class"].astype("string").str.strip()
    df["source_dataset"] = df["source_dataset"].astype("string").str.strip()
    df["orig_split"] = df["split"].astype("string").str.strip().str.lower().map(SPLIT_ALIASES)
    n_total = len(df)

    # ---- exclusions (documented rules)
    reason = pd.Series("", index=df.index, dtype="string")
    bad_food = df["food"].isna() | df["food"].str.lower().isin(BAD_TOKENS)
    reason[bad_food] = "invalid_or_unknown_food_label"
    unreadable = ~(df["exists"].astype(bool) & df["decode_ok"].astype(bool)) | (df["dhash"].str.len() != 16)
    reason[(reason == "") & unreadable] = "image_missing_or_unreadable"
    live = df[reason == ""]
    sh = live[live.sha256 != ""].groupby("sha256")["food"].nunique()
    conflict_hashes = set(sh[sh > 1].index)
    reason[(reason == "") & df["sha256"].isin(conflict_hashes)] = "byte_identical_images_with_conflicting_food_labels"
    excl = df[reason != ""].assign(exclusion_reason=reason[reason != ""])
    excl[["image_id", "image_name", "image_path", "food", "source_dataset", "sha256", "exclusion_reason"]].to_csv(
        DATA_PREP / "excluded_samples.csv", index=False)
    inc = df[reason == ""].reset_index(drop=True)
    if inc.empty:
        print("ERROR: no usable images after exclusions.")
        return 1

    # ---- labels
    names = sorted(inc["food"].unique())
    inc["class_id"] = inc["food"].map({n: i for i, n in enumerate(names)}).astype(int)
    fr = derive_freshness(inc, args.accept_folder_rule)
    inc = pd.concat([inc, fr], axis=1)
    best = inc["freshness_label"].where(inc["freshness_trainable"], inc["freshness_candidate"].fillna("Unknown"))
    inc["strat_key"] = inc["food"].astype(str) + "|" + best.astype(str)
    inc["is_augmented_copy"] = inc["image_name"].astype("string").str.match(AUG_RE.pattern, case=False)
    inc["family_key"] = make_family_key(inc)

    # ---- groups
    m = len(inc)
    dsu = DSU(m)
    stats = {"family_merges": 0, "exact_merges": 0, "near_merges": 0, "near_capped_skips": 0}
    for _, idx in inc.groupby("family_key").indices.items():
        for k in idx[1:]:
            stats["family_merges"] += dsu.union(int(idx[0]), int(k)) == "merged"
    for _, idx in inc[inc.sha256 != ""].groupby("sha256").indices.items():
        for k in idx[1:]:
            stats["exact_merges"] += dsu.union(int(idx[0]), int(k)) == "merged"
    vals = hash_values(inc["dhash"])
    print(f"Building near-duplicate groups for {m:,} images (dHash distance <= {args.near_dup_distance}) ...", flush=True)
    for d in range(args.near_dup_distance + 1):
        for i, j in iter_near_pairs(vals, d):
            r = dsu.union(i, j, cap=args.max_group_size)
            stats["near_merges"] += r == "merged"
            stats["near_capped_skips"] += r == "capped"
    roots = np.array([dsu.find(i) for i in range(m)])
    first_pos = pd.Series(np.arange(m)).groupby(roots).transform("min").to_numpy()
    inc["group_id"] = pd.factorize(first_pos)[0]
    inc["group_size"] = inc.groupby("group_id")["image_id"].transform("size")

    # ---- split
    ratios = tuple(args.ratios)
    inc["new_split"] = assign_groups(inc, ratios, args.seed)

    # ---- manifest
    cols = ["image_id", "image_name", "image_path", "food", "class_id", "source_dataset", "class", "orig_split", "new_split",
            "group_id", "group_size", "is_augmented_copy", "family_key", "sha256", "dhash", "condition_original",
            "freshness_candidate", "freshness_candidate_source", "freshness_label", "freshness_label_source", "freshness_trainable"]
    man = inc[cols].rename(columns={"orig_split": "original_split"})
    man.to_csv(DATA_PREP / "split_manifest.csv", index=False)

    # ---- validation
    checks, near_pairs = verify(man, args.near_dup_distance)
    near_pairs.to_csv(OUT_REPORTS / "near_duplicate_conflicts.csv", index=False)
    checks.to_csv(OUT_REPORTS / "leakage_checks.csv", index=False)
    hard_fail = (checks[(checks.type == "hard")].result != "PASS").any()

    # ---- reports
    lab_conf = man.groupby("group_id")["food"].nunique()
    conf_groups = lab_conf[lab_conf > 1].index
    man[man.group_id.isin(conf_groups)][["image_id", "image_name", "group_id", "food", "new_split"]].sort_values(
        ["group_id"]).to_csv(OUT_REPORTS / "label_conflict_groups.csv", index=False)
    dist = man.groupby(["food", "new_split"]).size().unstack(fill_value=0).reindex(columns=list(SPLITS), fill_value=0)
    dist["total"] = dist.sum(axis=1)
    for s in SPLITS:
        dist[f"{s}_%"] = (dist[s] / dist["total"] * 100).round(1)
    dist.insert(0, "class_id", [names.index(f) for f in dist.index])
    dist = dist.reset_index()
    dist.to_csv(OUT_REPORTS / "class_distribution_by_split.csv", index=False)
    train = man[man.new_split == "train"]
    cnt = train["food"].value_counts()
    k_cls = len(names)
    weights = {n: round(len(train) / (k_cls * int(cnt.get(n, 0))), 6) for n in names if cnt.get(n, 0) > 0}
    (OUT_REPORTS / "class_weights.json").write_text(json.dumps({
        "formula": "weight_c = N_train / (n_classes * n_train_c)", "computed_on": "train split images after exclusions",
        "n_train": int(len(train)), "n_classes": k_cls, "class_names_in_class_id_order": names, "weights": weights}, indent=2))
    src_hash_after = sha256_file(food_csv)
    config = {
        "script": "prepare_splits.py", "version": SCRIPT_VERSION, "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "seed": args.seed, "ratios": list(ratios), "near_dup_distance": args.near_dup_distance,
        "max_group_size": args.max_group_size, "accept_folder_rule": args.accept_folder_rule,
        "source_food_csv": str(food_csv), "source_food_csv_sha256_before": src_hash_before,
        "source_food_csv_sha256_after": src_hash_after, "source_unchanged": src_hash_before == src_hash_after,
        "image_scan_csv_sha256": sha256_file(scan_file),
        "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
        "rows_in_source": n_total, "rows_included": int(len(man)), "rows_excluded": int(len(excl)), "group_stats": stats,
        "validation_hard_checks_passed": not hard_fail,
    }
    (DATA_PREP / "split_config.json").write_text(json.dumps(config, indent=2, default=int))
    write_report(args, df, excl, man, dist, weights, checks, near_pairs, stats, conf_groups, names, fr, config)

    print("\n================ PHASE 3 SUMMARY ================")
    print(f"Source rows {n_total:,} | included {len(man):,} | excluded {len(excl):,} | groups {man.group_id.nunique():,}")
    print("Split sizes: " + ", ".join(f"{s}={int((man.new_split == s).sum()):,}" for s in SPLITS))
    print(checks[["check", "result", "detail"]].to_string(index=False))
    print(f"Source CSV unchanged: {config['source_unchanged']}")
    print(f"Report: {OUT_REPORTS / 'phase3_report.md'}")
    return 1 if hard_fail else 0


def write_report(args, df, excl, man, dist, weights, checks, near_pairs, stats, conf_groups, names, fr, config) -> None:
    L: list[str] = []
    h = lambda t, n=2: L.extend(["", f"{'#' * n} {t}", ""])
    p = lambda t: L.extend([t, ""])
    L.append("# SmartPlateAI - Phase 3 Split Report")
    p(f"Generated {config['generated']} | script v{SCRIPT_VERSION} | seed {args.seed} | ratios {tuple(args.ratios)} | "
      f"near-duplicate distance <= {args.near_dup_distance} | max near-merge group size {args.max_group_size}")
    h("1. Leakage validation")
    L.append(md_table(checks))
    p("`FAIL` on a hard check means the split is invalid. `REVIEW` means near-duplicate pairs remain across splits "
      "(see section 6 and near_duplicate_conflicts.csv).")
    h("2. Exclusions")
    p(f"Source rows: {len(df):,}. Included: {len(man):,}. Excluded: {len(excl):,} (list: data_prep\\excluded_samples.csv).")
    L.append(md_table(excl["exclusion_reason"].value_counts().rename_axis("reason").reset_index(name="images")))
    h("3. Group construction")
    sizes = man.drop_duplicates("group_id")["group_size"]
    p(f"Groups: {man.group_id.nunique():,} for {len(man):,} images. Multi-image groups: {int((sizes > 1).sum()):,} "
      f"(largest {int(sizes.max())} images). Merges: family {stats['family_merges']:,}, exact-duplicate {stats['exact_merges']:,}, "
      f"near-duplicate {stats['near_merges']:,}; near-duplicate merges refused by the size cap: {stats['near_capped_skips']:,}.")
    L.append(md_table(sizes.value_counts().sort_index().rename_axis("group_size").reset_index(name="groups"), 15))
    p(f"Groups whose images carry more than one food label: {len(conf_groups):,} (kept together in one split; listed in "
      "label_conflict_groups.csv for manual review). Byte-identical images with conflicting labels were excluded (section 2).")
    h("4. Split result")
    p("Image counts: " + ", ".join(f"{s}={int((man.new_split == s).sum()):,} ({(man.new_split == s).mean() * 100:.1f}%)" for s in SPLITS))
    L.append(md_table(dist, 40))
    orig = man[~man.is_augmented_copy.astype(bool)]
    p("Original (non-augmented) images per split - use these for headline test metrics, because pre-augmented rotated/shifted copies "
      "do not resemble real user photos: " + ", ".join(f"{s}={int((orig.new_split == s).sum()):,}" for s in SPLITS))
    L.append(md_table(pd.crosstab(man.source_dataset, man.new_split).reindex(columns=list(SPLITS), fill_value=0).reset_index()))
    h("5. Class imbalance and class weights (computed on the train split only)")
    cnt = man[man.new_split == "train"]["food"].value_counts()
    imb = cnt.max() / max(cnt.min(), 1)
    p(f"Train imbalance ratio {imb:.1f}x (largest {int(cnt.max()):,}, smallest {int(cnt.min()):,}). Remedy for training: the class weights in "
      "reports\\phase3\\class_weights.json plus macro-averaged metrics. No resampling or augmentation was applied in this phase.")
    L.append(md_table(pd.DataFrame({"food": list(weights), "train_images": [int(cnt[n]) for n in weights], "class_weight": list(weights.values())})))
    h("6. Near-duplicate residuals")
    p(f"Near-duplicate pairs still crossing splits: {len(near_pairs):,}"
      + (" (first 5,000 listed)" if len(near_pairs) >= 5000 else "") + ". Non-zero only when the group-size cap refused a merge.")
    h("7. Freshness / condition labels")
    p(f"`condition` values are never inferred from food names. Rule R1 (documented): for source FruitQuality1 only, the source folder name "
      f"(freshapples, rottenapples, freshbanana, ...) must equal the CSV `class` and map to the CSV `food`; then it is a *candidate* label. "
      f"Candidates are used for stratification only. They become training labels only if you run with --accept-folder-rule "
      f"(accepted this run: {args.accept_folder_rule}). Original-label vs class contradictions set to Unknown: {fr.attrs['conflicts']}; "
      f"candidate families with inconsistent labels dropped: {fr.attrs['family_conflicts']}.")
    ls = man.groupby(["freshness_label_source", "freshness_label"]).size().rename("images").reset_index()
    L.append(md_table(ls))
    cand = int(man["freshness_candidate"].notna().sum())
    p(f"Images with a pending R1 candidate label: {cand:,}. Trainable freshness images now: {int(man.freshness_trainable.sum()):,}. "
      "Everything else stays Unknown and is excluded from freshness training.")
    tr = man[man.freshness_trainable]
    if len(tr):
        L.append(md_table(tr.groupby(["food", "freshness_label", "new_split"]).size().unstack(fill_value=0)
                          .reindex(columns=list(SPLITS), fill_value=0).reset_index()))
    h("8. Packaged-food nutrition and additive data")
    p("Not part of the image split. Phase 1 data-quality flags are unchanged and nothing was repaired or imputed.")
    for f in ("packaged_food_flags.csv", "additive_extraction_gaps.csv"):
        fp = REPORTS_DIR / f
        p(f"- `{f}`: {len(pd.read_csv(fp)):,} flagged rows" if fp.is_file() else f"- `{f}`: not found")
    h("9. Assumptions and limitations")
    L.extend([
        "- Groups link images by filename family, identical bytes and 64-bit dHash distance <= "
        f"{args.near_dup_distance}. The dHash comparison is exhaustive (no bucket is skipped), but dHash only detects resized, "
        "re-compressed or lightly edited copies. Rotated, flipped, cropped or strongly recoloured copies of one photo, and different photos of "
        "the same object, are NOT detected unless their filename prefix is in the augmentation list.",
        "- Residual leakage from undetected augmentations is therefore possible. Spot-check a few test images against train before trusting any test score.",
        f"- Near-duplicate merges are capped at {args.max_group_size} images per group to stop chains of similar flat/white-background photos from "
        "forming giant groups; refused merges appear in section 6.",
        "- Source confounding remains: fast-food classes come from one image source and most fruit/vegetable classes from one source each.",
        "- Stratification is by food plus best-available condition (original label, else pending candidate, else Unknown).",
        "- No model was trained and no accuracy is claimed.", ""])
    (OUT_REPORTS / "phase3_report.md").write_text("\n".join(L), encoding="utf-8")


def validate_only(args) -> int:
    mf = DATA_PREP / "split_manifest.csv"
    if not mf.is_file():
        print("ERROR: data_prep\\split_manifest.csv not found. Run without --validate-only first.")
        return 1
    man = pd.read_csv(mf, dtype={"image_id": str, "dhash": str, "sha256": str}, low_memory=False)
    man["sha256"] = man["sha256"].fillna("")
    cfg = json.loads((DATA_PREP / "split_config.json").read_text()) if (DATA_PREP / "split_config.json").is_file() else {}
    checks, _ = verify(man, int(cfg.get("near_dup_distance", args.near_dup_distance)))
    print(checks[["check", "result", "detail"]].to_string(index=False))
    return 1 if (checks[checks.type == "hard"].result != "PASS").any() else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="SmartPlateAI Phase 3: group-aware split (no training).")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ratios", type=float, nargs=3, default=[0.70, 0.15, 0.15], metavar=("TRAIN", "VAL", "TEST"))
    ap.add_argument("--near-dup-distance", type=int, choices=[0, 1, 2, 3], default=2)
    ap.add_argument("--max-group-size", type=int, default=2000)
    ap.add_argument("--accept-folder-rule", action="store_true", help="Promote rule-R1 candidate freshness labels to training labels.")
    ap.add_argument("--food-csv"); ap.add_argument("--scan")
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()
    if abs(sum(args.ratios) - 1.0) > 1e-6:
        print("ERROR: --ratios must sum to 1.")
        return 1
    return validate_only(args) if args.validate_only else build(args)


if __name__ == "__main__":
    sys.exit(main())