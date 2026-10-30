"""What each of the 24 classes' nutrition record actually describes, and which classes name a CATEGORY of dishes.

The project's nutrition dataset links every class to one USDA FoodData Central record (fdc_id) but stores no description.
The descriptions below were retrieved from the FDC API on 2026-10-27 for exactly those fdc_ids, so the app can say which
food the numbers belong to. A description is only shown when the dataset's fdc_id for the class matches the one here.

CATEGORY classes: the image model recognises the category (e.g. "Sandwich") but cannot tell fillings or toppings apart,
while the linked record is one specific variant (a chicken submarine sandwich). For these, nutrition is not shown as the
food's nutrition automatically: the user picks the specific type, or explicitly accepts the clearly labelled generic record.
"""
from __future__ import annotations

FDC_FOOD_URL = "https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients"

# class -> (fdc_id, USDA data type, USDA description)
CLASS_RECORDS: dict[str, tuple[int, str, str]] = {
    "Apple": (171688, "SR Legacy", "Apples, raw, with skin (Includes foods for USDA's Food Distribution Program)"),
    "Baked Potato": (170093, "SR Legacy", "Potatoes, baked, flesh and skin, without salt"),
    "Banana": (173944, "SR Legacy", "Bananas, raw"),
    "Bell Pepper": (170427, "SR Legacy", "Peppers, sweet, green, raw"),
    "Burger": (170693, "SR Legacy", "Fast foods, hamburger; single, regular patty; plain"),
    "Carrot": (170393, "SR Legacy", "Carrots, raw"),
    "Crispy Chicken": (170343, "SR Legacy", "KFC, Fried Chicken, EXTRA CRISPY, Skin and Breading"),
    "Cucumber": (168409, "SR Legacy", "Cucumber, with peel, raw"),
    "Donut": (174990, "SR Legacy", "Doughnuts, cake-type, plain (includes unsugared, old-fashioned)"),
    "Fries": (169836, "SR Legacy", "Restaurant, family style, french fries"),
    "Grape": (174683, "SR Legacy", "Grapes, red or green (European type, such as Thompson seedless), raw"),
    "Guava": (173044, "SR Legacy", "Guavas, common, raw"),
    "Hot Dog": (171633, "SR Legacy", "Frankfurter, meat and poultry, cooked, boiled"),
    "Jujube": (168151, "SR Legacy", "Jujube, raw"),
    "Mango": (169910, "SR Legacy", "Mangos, raw"),
    "Orange": (169097, "SR Legacy", "Oranges, raw, all commercial varieties"),
    "Pizza": (170317, "SR Legacy", "Pizza, cheese topping, regular crust, frozen, cooked"),
    "Pomegranate": (169134, "SR Legacy", "Pomegranates, raw"),
    "Potato": (170026, "SR Legacy", "Potatoes, flesh and skin, raw"),
    "Sandwich": (170309, "SR Legacy", "Fast foods, submarine sandwich, oven roasted chicken on white bread with lettuce and tomato"),
    "Strawberry": (167762, "SR Legacy", "Strawberries, raw"),
    "Taco": (170689, "SR Legacy", "Fast foods, taco with beef, cheese and lettuce, hard shell"),
    "Taquito": (169771, "SR Legacy", "Taquitos, frozen, chicken and cheese, oven-heated"),
    "Tomato": (170457, "SR Legacy", "Tomatoes, red, ripe, raw, year round average"),
}

# Category classes -> specific types offered to the user. Each choice is looked up in USDA FoodData Central by its own
# name; when USDA has no clearly matching record (e.g. paneer sandwich) the app says so instead of substituting.
CATEGORY_VARIANTS: dict[str, list[str]] = {
    "Sandwich": ["Paneer sandwich", "Vegetable sandwich", "Cheese sandwich", "Chicken sandwich", "Egg sandwich", "Ham sandwich",
                 "Peanut butter sandwich"],
    "Burger": ["Hamburger", "Cheeseburger", "Veggie burger", "Chicken burger"],
    "Pizza": ["Cheese pizza", "Pepperoni pizza", "Vegetable pizza", "Chicken pizza"],
    "Taco": ["Beef taco", "Chicken taco", "Bean taco", "Fish taco"],
    "Taquito": ["Chicken taquito", "Beef taquito"],
    "Hot Dog": ["Hot dog with bun", "Frankfurter"],
    "Crispy Chicken": ["Fried chicken breast", "Fried chicken drumstick", "Chicken nuggets"],
    "Donut": ["Glazed doughnut", "Chocolate doughnut", "Cake doughnut", "Filled doughnut"],
}

# Short warning shown with the generic record of a category class: what the record is, in plain words.
GENERIC_CAVEATS: dict[str, str] = {
    "Sandwich": "This record is a chicken submarine sandwich on white bread.",
    "Burger": "This record is a plain single-patty beef hamburger.",
    "Pizza": "This record is a frozen cheese pizza.",
    "Taco": "This record is a hard-shell beef taco with cheese and lettuce.",
    "Taquito": "This record is frozen chicken-and-cheese taquitos.",
    "Hot Dog": "This record is the frankfurter only, without the bun or toppings.",
    "Crispy Chicken": "This record is the skin and breading of extra-crispy fried chicken only, not the meat.",
    "Donut": "This record is a plain cake-type doughnut (no glaze, icing or filling).",
}


def is_category(food: str | None) -> bool:
    return bool(food) and food in CATEGORY_VARIANTS


def record_for(food: str, fdc_id: int | None) -> dict | None:
    """The USDA identity of a class's nutrition record, only if the dataset really uses that record."""
    rec = CLASS_RECORDS.get(food)
    if not rec or fdc_id is None or int(fdc_id) != rec[0]:
        return None
    return {"fdc_id": rec[0], "data_type": rec[1], "description": rec[2], "url": FDC_FOOD_URL.format(fdc_id=rec[0])}


def category_for_name(name: str | None) -> str | None:
    """The category class a free-text food name belongs to ('Paneer sandwich' -> 'Sandwich'), if any."""
    if not name:
        return None
    low = name.casefold()
    for cls, variants in CATEGORY_VARIANTS.items():
        if any(v.casefold() == low for v in variants):
            return cls
    heads = {"Sandwich": ("sandwich", "sub"), "Burger": ("burger",), "Pizza": ("pizza",), "Taco": ("taco",), "Taquito": ("taquito",),
             "Hot Dog": ("hot dog", "frankfurter"), "Crispy Chicken": ("fried chicken", "chicken nugget"),
             "Donut": ("donut", "doughnut")}
    words = " " + " ".join(low.replace("-", " ").split()) + " "
    for cls, keys in heads.items():
        if any(f" {k} " in words or f" {k}s " in words for k in keys):
            return cls
    return None
