"""Groups of ImageNet-1k classes used to describe what the ORIGINAL ImageNet MobileNetV2 (already loaded for the food-mass
signal) thinks an image mainly shows. Pure Python, unit-testable.

The signal is categorical: the group of ImageNet's single most likely class (its top-1). No new probability threshold is
involved. The groups come from the ImageNet class meanings, not from tuning on evaluation photos:
  food       the food classes already used for the food-mass signal (recognizer.IMAGENET_FOOD_INDICES)
  container  generic packaging that may or may not hold food (packet, carton, bottles, jugs, cans, bags, a shop shelf)
  product    specific NON-food products and objects (medicine bottle, cosmetics, toiletries, phone, books, paper goods)
  other      everything else
A container is NOT evidence of food: a carton can hold medicine and a packet can hold seeds. It only means "this looks like a
package, so read its label", and it is never used to accept an image as food.
"""
from __future__ import annotations

CONTAINER = {
    440: "beer_bottle", 455: "bottlecap", 478: "carton", 509: "confectionery", 582: "grocery_store", 653: "milk_can",
    692: "packet", 728: "plastic_bag", 737: "pop_bottle", 790: "shopping_basket", 791: "shopping_cart", 898: "water_bottle",
    899: "water_jug", 901: "whiskey_jug", 907: "wine_bottle",
}
PRODUCT = {
    487: "cellular_telephone", 549: "envelope", 585: "hair_spray", 631: "lotion", 681: "notebook", 700: "paper_towel",
    709: "pencil_box", 711: "perfume", 720: "pill_bottle", 804: "soap_dispenser", 838: "sunscreen", 917: "comic_book",
    921: "book_jacket", 999: "toilet_tissue",
}


def group_of(index: int, food_indices: set[int] | list[int]) -> str:
    if index in set(food_indices):
        return "food"
    if index in CONTAINER:
        return "container"
    if index in PRODUCT:
        return "product"
    return "other"
