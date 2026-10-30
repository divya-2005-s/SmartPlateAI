"""The production class mapping and freshness configuration must stay exactly as the models were trained.
Reads the real config files (no TensorFlow): a reordered or edited class list would silently mislabel every prediction."""
import json
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
CLASSES_FILE = BACKEND / "models" / "production" / "food_classifier" / "class_names.json"
FRESHNESS_FILE = BACKEND / "models" / "production" / "freshness" / "freshness_config.json"
EXPECTED = ["Apple", "Baked Potato", "Banana", "Bell Pepper", "Burger", "Carrot", "Crispy Chicken", "Cucumber", "Donut", "Fries",
            "Grape", "Guava", "Hot Dog", "Jujube", "Mango", "Orange", "Pizza", "Pomegranate", "Potato", "Sandwich", "Strawberry",
            "Taco", "Taquito", "Tomato"]
FRESHNESS = ["Apple", "Banana", "Bell Pepper", "Carrot", "Cucumber", "Grape", "Guava", "Jujube", "Mango", "Orange",
             "Pomegranate", "Potato", "Strawberry", "Tomato"]


@pytest.mark.skipif(not CLASSES_FILE.is_file(), reason="production model not installed")
def test_food_classifier_has_the_trained_24_classes_in_output_order():
    meta = json.loads(CLASSES_FILE.read_text(encoding="utf-8"))
    assert meta["class_names"] == EXPECTED
    assert meta["class_id_to_name"] == {str(i): n for i, n in enumerate(EXPECTED)}  # output index -> label
    assert meta["input"]["shape"] == [224, 224, 3] and "preprocessing is inside the model" in meta["input"]["dtype"]


@pytest.mark.skipif(not FRESHNESS_FILE.is_file(), reason="freshness model not installed")
def test_freshness_model_covers_14_produce_classes_of_the_food_model():
    cfg = json.loads(FRESHNESS_FILE.read_text(encoding="utf-8"))
    assert cfg["supported_foods"] == FRESHNESS and set(FRESHNESS) <= set(EXPECTED)
    assert cfg["food_model_sha256"] and "test_metrics" in cfg  # bound to one food model; evaluated on the test split
    assert cfg["t_fresh"] <= cfg["t_spoiled"]
