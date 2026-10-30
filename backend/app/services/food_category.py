"""Food category for display (Fruits, Vegetables, ...). Category is not freshness and says nothing about safety.

Order of evidence: a valid category from the OpenAI structured response, else a keyword rule on the food name,
else "Other". Only the fixed set below is ever returned.
"""
from __future__ import annotations

import re

CATEGORIES = ["Fruits", "Vegetables", "Cooked Dishes", "Bakery Items", "Snacks", "Beverages", "Dairy", "Grains & Cereals",
              "Meat, Fish & Eggs", "Packaged Food", "Other"]

_RULES: list[tuple[str, str]] = [
    ("Beverages", r"\b(juice|tea|coffee|milkshake|shake|smoothie|lassi|soda|cola|drink|water|beer|wine|buttermilk|chaas)\b"),
    ("Bakery Items", r"\b(bread|bun|cake|cookie|biscuit|croissant|muffin|pastry|donut|doughnut|bagel|rusk|pav|toast)\b"),
    ("Cooked Dishes", r"\b(pizza|burger|taco|burrito|sandwich|biryani|curry|dal|daal|sambar|dosa|idli|vada|samosa|pasta|noodles?|"
                      r"fried rice|khichdi|upma|poha|paratha|roti|chapati|naan|puri|soup|momo|dumpling|omelette|stew|salad|"
                      r"french fries|fries|hot ?dog|paneer|chole|rajma|kebab|tikka)\b"),
    ("Snacks", r"\b(chips|crisps|namkeen|bhujia|popcorn|cracker|nachos|chocolate|candy|wafer|pretzel)\b"),
    ("Dairy", r"\b(milk|cheese|curd|yog(h)?urt|butter|ghee|cream)\b"),
    ("Meat, Fish & Eggs", r"\b(chicken|mutton|beef|pork|fish|prawn|shrimp|egg|eggs|crab|lamb)\b"),
    ("Grains & Cereals", r"\b(rice|wheat|oats|millet|quinoa|corn flakes|cereal|barley|ragi|jowar|bajra)\b"),
    ("Fruits", r"\b(apple|banana|mango|orange|grapes?|guava|papaya|watermelon|melon|pineapple|pomegranate|pear|peach|plum|"
               r"cherr(y|ies)|kiwi|lemon|lime|strawberr(y|ies)|berr(y|ies)|apricot|fig|dates?|lychee|litchi|jackfruit|"
               r"custard apple|sapota|chikoo|coconut|avocado|tangerine|mandarin|mosambi|grapefruit|fruit)\b"),
    ("Vegetables", r"\b(onion|tomato|potato|carrot|cabbage|cauliflower|cucumber|brinjal|eggplant|aubergine|spinach|capsicum|"
                   r"bell pepper|chil+i|beetroot|beet|radish|okra|bhindi|lady ?finger|pumpkin|gourd|peas|beans|garlic|ginger|"
                   r"broccoli|lettuce|zucchini|mushroom|sweet potato|yam|turnip|leek|celery|corn|maize|drumstick|vegetable)\b"),
]


def from_name(name: str | None) -> str:
    n = (name or "").lower()
    # Dishes made from produce ("tomato soup", "potato chips") must not be called raw produce: dish/snack rules come first.
    for cat, pat in _RULES:
        if re.search(pat, n):
            return cat
    return "Other"


def resolve(name: str | None, provider_category: str | None = None) -> str:
    if provider_category in CATEGORIES and provider_category != "Other":
        return provider_category
    return from_name(name)
