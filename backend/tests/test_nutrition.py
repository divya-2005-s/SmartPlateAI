import pandas as pd

from app.services.nutrition import NutritionReference


def make_csv(tmp_path):
    p = tmp_path / "food.csv"
    pd.DataFrame({"food": ["Apple", "Apple", "Jujube"], "fdc_id": [1, 1, 2], "energy_kcal": [52.0, 52.0, 79.0],
                  "fiber_g": [2.4, 2.4, None], "vitamin_c_mg": [4.6, 4.6, 69.0]}).to_csv(p, index=False)
    return p


def test_known_food_per_100g_and_serving(tmp_path):
    n = NutritionReference(make_csv(tmp_path)).lookup("Apple", 150)
    energy = next(x for x in n["nutrients"] if x["key"] == "energy_kcal")
    assert energy["per_100g"] == 52.0 and energy["per_serving"] == 78.0 and energy["unit"] == "kcal"
    assert n["is_estimate"] is True and n["source_fdc_id"] == 1


def test_missing_nutrient_stays_missing_not_zero(tmp_path):
    n = NutritionReference(make_csv(tmp_path)).lookup("Jujube", 100)
    fiber = next(x for x in n["nutrients"] if x["key"] == "fiber_g")
    assert fiber["per_100g"] is None and fiber["per_serving"] is None and "Fiber" in n["not_available"]


def test_no_serving_means_no_scaled_values(tmp_path):
    n = NutritionReference(make_csv(tmp_path)).lookup("Apple")
    assert all(x["per_serving"] is None for x in n["nutrients"])


def test_unknown_food_and_missing_file(tmp_path):
    assert NutritionReference(make_csv(tmp_path)).lookup("Dragon fruit") is None
    ref = NutritionReference(tmp_path / "nope.csv")
    assert ref.lookup("Apple") is None and ref.error