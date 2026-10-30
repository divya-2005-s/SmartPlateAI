"""Label parser on realistic layouts. Texts marked REAL are Tesseract output from real Open Food Facts photos in
data_eval/packaged (Sting 8902080000227, Good Day 8901063093522, Parle-G 8901719125478); the others are typical layouts.
Rule under test: a value is shown only when it is read next to its own nutrient name, from the nutrition panel, with a
plausible amount; everything else stays missing (or is listed as unreadable), and the column basis is never guessed."""
import pytest

from app.services.label_parser import extract_nutrition, parse_label

STING_REAL = """WUTRITIONAL INFORMATION PER 100ml (APPROX.): ENERGY: 28kcal, TOTAL CARBOHYDRATE: 7g, OF WHICH SUGARS: 7g,
TOTAL FAT: Og, SATURATED FAT: Og, TRANS FAT: iM PROTEIN: 0g, SODIUM: Sy bay B3: 1.9mg, VITAMIN B6: U.2mg,
VITAMIN B12: 0.2meg. {GUIDELINE DAILY AMOUNT (2000kcal DIET) APPROX.
INGREDIENTS: CARBONATED WATER, SUGAR, ACIDITY REGULATORS (330, 331) STONY (452li), 385), TAURINE,"""

GOOD_DAY_REAL = """NUTRITION INFORMATION
PER 100g PRODUCT (APPROX.)
Carbohydrates
of which Sugars
Protein
Energy
IREREDIENTS: REFINED WHEAT FLOUR (MAIDA), EDISLE VEGETABLE OM (PALM), SUGAR, CASHEW NUTS (4.5%), INVERT
SYRUP, MILK SOLIDS, BUTTER GG) RAISING AGENTS [e008] & SOUTH. JODISED SALT AND EMOLSIFIERS (322, 471, 4720)"""

PARLE_G_REAL = """NUTRITIONAL INFORMATION~
SERVE SIZE� 15 Q PER SERVE
ENERGY (kcal)
TOTALSUGARS(g) 25.5
TOTAL FAT (g) 13.0
SODIUM (mg) 296"""


def values(text):
    return {k: v["value"] for k, v in extract_nutrition(text)["values"].items()}


def test_paragraph_label_reads_every_value_with_its_own_name():
    v = values(STING_REAL)  # REAL: one line holds energy, carbohydrate and sugars
    assert v == {"energy_kcal": 28.0, "carbohydrate_g": 7.0, "total_sugars_g": 7.0, "protein_g": 0.0}


def test_number_belonging_to_another_field_is_not_taken():
    v = values(STING_REAL)
    assert "sodium_mg" not in v  # "SODIUM: Sy bay B3: 1.9mg" - 1.9 is vitamin B3
    assert "trans_fat_g" not in v  # "TRANS FAT: iM PROTEIN: 0g" - the 0 is protein's


def test_ingredient_list_never_supplies_nutrition_values():
    assert values(GOOD_DAY_REAL) == {}  # REAL: table numbers unreadable; "SUGAR, CASHEW NUTS (4.5%)" is not 4.5 g sugar
    assert "total_sugars_g" not in values(STING_REAL.replace("OF WHICH SUGARS: 7g,", ""))  # "SUGAR ... (330" is an INS code


def test_merged_serving_line_leaves_the_basis_unknown():
    n = extract_nutrition(PARLE_G_REAL)  # REAL: the "AMOUNT PER 100g" heading was lost
    assert n["basis"] == "unknown" and "serving-size line" in n["basis_note"]


@pytest.mark.parametrize("text,basis,expected", [
    ("NUTRITIONAL INFORMATION\nAmount Per 100 g Per Serve (30 g)\nEnergy (kcal) 480 144\nProtein (g) 7.0 2.1\nTotal Fat (g) 22 6.6",
     "per 100 g", {"energy_kcal": 480.0, "protein_g": 7.0, "total_fat_g": 22.0}),
    ("Nutrition Facts\nServing size 30 g\nAmount per serving\nCalories 120\nTotal Fat 3 g\nSodium 160 mg",
     "per serving", {"energy_kcal": 120.0, "total_fat_g": 3.0, "sodium_mg": 160.0}),
    ("Nutrition information\nTypical values per 100 g\nEnergy 2252 kJ / 539 kcal\nFat 30.9 g\nof which saturates 10.6 g\nSalt 0.107 g",
     "per 100 g", {"energy_kcal": 538.2, "total_fat_g": 30.9, "saturated_fat_g": 10.6}),
])
def test_common_layouts(text, basis, expected):
    n = extract_nutrition(text)
    assert n["basis"] == basis and {k: v["value"] for k, v in n["values"].items()} == expected


def test_percentages_are_not_amounts():
    v = values("Nutrition information per 100 g\nProtein 12%\nTotal fat 9 g 14%")
    assert "protein_g" not in v and v["total_fat_g"] == 9.0


def test_impossible_per_100g_value_is_withheld_and_reported():
    n = extract_nutrition("Nutrition information per 100 g\nTotal sugars 330 g\nProtein 6 g")
    assert "total_sugars_g" not in n["values"] and n["values"]["protein_g"]["value"] == 6.0
    assert n["unreadable"][0]["key"] == "total_sugars_g" and "not possible" in n["unreadable"][0]["reason"]


def test_partial_ocr_keeps_only_what_was_read():
    n = extract_nutrition("Energy 120 kcal\nProtein")  # cropped photo: no heading, protein value cut off
    assert n["basis"] == "unknown" and {k: v["value"] for k, v in n["values"].items()} == {"energy_kcal": 120.0}


def test_original_ocr_text_is_kept_with_each_value():
    n = extract_nutrition(STING_REAL)
    assert n["values"]["energy_kcal"]["raw"].startswith("WUTRITIONAL INFORMATION PER 100ml")
    assert parse_label(STING_REAL)["nutrition"]["source"] == "package label (OCR)"
