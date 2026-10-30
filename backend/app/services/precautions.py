"""Food-specific handling precautions for unpackaged foods.

General guidance based on WHO "Five Keys to Safer Food", FSSAI consumer guidance and USDA/FDA produce-safety advice.
It is labelled as general guidance, separated from product-specific (label) instructions, and never claims that
washing removes all residues or that a food is safe because it looks fresh.
"""
from __future__ import annotations

import re

PRODUCE = r"apple|banana|orange|mango|grape|guava|papaya|pineapple|pomegranate|watermelon|melon|lemon|lime|strawberr|berry|cherry|" \
          r"pear|peach|plum|kiwi|tomato|potato|onion|garlic|carrot|cucumber|cabbage|cauliflower|broccoli|spinach|lettuce|okra|" \
          r"eggplant|brinjal|capsicum|pepper|chil+i|pumpkin|gourd|beans|peas|corn|beetroot|radish|ginger|coriander|mint|fruit|vegetable"
THICK_PEEL = r"banana|orange|mango|papaya|pineapple|watermelon|melon|pomegranate|lemon|lime"
RAW_ANIMAL = r"chicken|meat|mutton|fish|prawn|shrimp|egg|beef|pork"
COOKED = r"pizza|burger|taco|burrito|sandwich|fries|samosa|dosa|idli|biryani|curry|dal|rice|noodle|pasta|momo|roll|cake|sweet|" \
         r"jalebi|ladoo|soup|paratha|roti|chapati|naan|puri|pakora|vada|hot dog|donut|doughnut"


def _p(text: str, kind: str = "general", source: str = "General food-safety guidance (WHO Five Keys / FSSAI)") -> dict:
    return {"kind": kind, "text": text, "source": source}


SPOILAGE_SOURCE = "USDA FSIS 'Molds on Food' guidance / WHO Five Keys (general guidance)"


def spoilage_precautions() -> list[dict]:
    """For food flagged as rotten or possibly spoiled. Never suggests eating it, or cutting away the bad part to eat the rest."""
    return [
        _p("Do not eat this food. Do not taste it to check, and do not sniff it closely: mouldy food can release spores that "
           "irritate the airways.", "danger", SPOILAGE_SOURCE),
        _p("Do not cut away the spoiled part and eat the rest. In soft or juicy foods, mould and bacteria can spread below the "
           "surface where they cannot be seen.", "danger", SPOILAGE_SOURCE),
        _p("Discard it in a closed bag or a covered bin so that spores do not spread to other food.", "warning", SPOILAGE_SOURCE),
        _p("Check food that was stored with it or touching it, and clean the container, shelf or fridge drawer it was in.",
           "warning", SPOILAGE_SOURCE),
        _p("Wash your hands with soap after handling it.", "warning"),
        _p("If someone has already eaten it and develops vomiting, diarrhoea, fever or difficulty breathing, seek medical advice.",
           "warning", "General medical guidance"),
    ]


def safety_alert(freshness: dict | None, food: str | None = None) -> dict | None:
    """Headline safety message derived from the freshness result; None when there is nothing to warn about."""
    st = (freshness or {}).get("status")
    basis = "SmartPlateAI freshness model (visual estimate only; a photo cannot prove that food is safe)"
    if st == "possibly_spoiled":
        return {"level": "danger", "title": "Possible spoilage detected: do not eat",
                "message": f"This photo shows visible signs that the {food or 'food'} may be rotten or spoiled. Do not eat it; discard it "
                           "safely. The nutrition shown is reference data for the fresh food and does not apply to spoiled food.",
                "basis": basis}
    if st == "uncertain":
        return {"level": "caution", "title": "Check before eating",
                "message": "Freshness could not be judged clearly from this photo. Inspect it for mould, sliminess, an off smell or "
                           "unusual colour, and discard it if you see any of these. When in doubt, throw it out.",
                "basis": basis}
    return None


def for_food(food: str, freshness: dict | None = None) -> list[dict]:
    f = food.lower()
    out: list[dict] = []
    if freshness:
        st = freshness.get("status")
        if st == "possibly_spoiled":
            # Consumption advice (washing before eating, cutting away bruises, cooking) does not apply to spoiled food.
            return spoilage_precautions()
        if st == "uncertain":
            out.append(_p("Freshness could not be judged reliably from this photo. Check it yourself for mould, softness, smell and colour.",
                          "warning", "SmartPlateAI freshness model (visual estimate only)"))
        elif st == "fresh":
            out.append(_p("Looking fresh in a photo does not prove the food is safe to eat; microbes and residues are invisible.", "info",
                          "SmartPlateAI freshness model (visual estimate only)"))
    if re.search(PRODUCE, f):
        out.append(_p("Wash under clean running water just before eating or cutting, and rub the surface with your hands. Do not use soap, "
                      "detergent or bleach.", source="FSSAI / FDA produce-washing guidance"))
        if re.search(THICK_PEEL, f):
            out.append(_p("Wash the outside even if you peel it, so that dirt and microbes on the skin are not transferred to the flesh by the knife.",
                          source="FDA produce-washing guidance"))
        out.append(_p("Washing reduces surface dirt, microbes and some residues, but it does not remove all pesticide residues or contaminants.",
                      "info"))
        out.append(_p("Cut away bruised or damaged areas, and keep cut produce refrigerated."))
        if re.search(r"potato", f):
            out.append(_p("Remove green skin and sprouts from potatoes; they contain higher levels of the natural toxicant solanine.",
                          source="Food-safety agencies (e.g. FSSAI, FDA)"))
    if re.search(RAW_ANIMAL, f):
        out.append(_p("Keep raw meat, fish and eggs separate from ready-to-eat foods, and wash hands, knives and boards after handling them."))
        out.append(_p("Cook thoroughly (for poultry, until the juices run clear and the centre reaches 75 °C / 165 °F)."))
    if re.search(COOKED, f):
        out.append(_p("Eat cooked food soon after preparation. Do not leave it at room temperature for more than 2 hours (1 hour in very hot weather)."))
        out.append(_p("Refrigerate leftovers promptly and reheat until steaming hot throughout; reheat only once."))
    out.append(_p("Wash your hands with soap before handling food."))
    return out
