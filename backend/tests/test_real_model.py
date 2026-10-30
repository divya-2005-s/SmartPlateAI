"""Tests against the REAL installed model. Skipped (reported as SKIPPED, not passed) when the model or genuine non-food images are absent."""
from pathlib import Path

import pandas as pd
import pytest

from app.ml.recognizer import FoodRecognizer, decode_upload

BACKEND = Path(__file__).resolve().parents[1]
MODEL_DIR = BACKEND / "models" / "production" / "food_classifier"
NONFOOD = BACKEND / "data_nonfood" / "general"

pytestmark = pytest.mark.skipif(not (MODEL_DIR / "best.keras").is_file(), reason="production model not installed")


@pytest.fixture(scope="module")
def rec():
    r = FoodRecognizer(MODEL_DIR)
    assert r.load(), r.status_message
    return r


def test_valid_food_images_return_structured_predictions(rec):
    man = pd.read_csv(BACKEND / "data_prep" / "split_manifest.csv", dtype={"image_id": str})
    sample = man[man.new_split == "val"].groupby("food").head(1).head(24)
    results = [rec.analyze_image(decode_upload(Path(p).read_bytes())) for p in sample.image_path]
    assert all(len(r["top_k"]) == 3 and 0 <= r["confidence"] <= 1 for r in results)
    print("accepted:", sum(r["decision"] == "accept" for r in results), "of", len(results))


def test_real_non_food_images_are_not_accepted_as_food(rec):
    imgs = sorted(p for p in NONFOOD.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}) if NONFOOD.is_dir() else []
    if len(imgs) < 20:
        pytest.skip("NOT RUN: fewer than 20 genuine non-food photos in data_nonfood\\general")
    decisions = [rec.analyze_image(decode_upload(p.read_bytes()))["decision"] for p in imgs]
    rejected = sum(d != "accept" for d in decisions) / len(decisions)
    print(f"non-food not accepted: {rejected:.1%} of {len(decisions)} (see reports\\rejection for the calibrated estimate)")
    assert rejected >= 0.5, "smoke floor only; the real estimate is in rejection_report.md"