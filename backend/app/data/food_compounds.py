"""Curated food -> notable compound mapping used by Chemical Intelligence.

Scope and rules:
- Only well-documented, textbook-level associations (e.g. lycopene in tomato, capsaicin in chilli).
- NO concentrations here. Amounts are shown only when a USDA FoodData Central record provides them.
- "where" notes describe where in the food a compound is mainly found, because presence varies by variety,
  ripeness, part (peel vs flesh) and preparation. Listing a compound does not mean a given sample contains it
  at any particular level.
Each compound: (common name, PubChem query name, category, role in the food, usda_nutrient_regex or None, where/notes)
"""
from __future__ import annotations

C = {
    "lycopene": ("Lycopene", "lycopene", "Carotenoid pigment", "Red colour of tomato, watermelon and pink guava; an antioxidant pigment.", r"lycopene", None),
    "beta_carotene": ("Beta-carotene", "beta-carotene", "Carotenoid pigment (provitamin A)", "Orange-yellow colour; the body can convert it to vitamin A.", r"carotene,? beta|beta.?carotene", None),
    "alpha_carotene": ("Alpha-carotene", "alpha-carotene", "Carotenoid pigment (provitamin A)", "Orange colour; partly convertible to vitamin A.", r"carotene,? alpha|alpha.?carotene", None),
    "ascorbic_acid": ("Vitamin C (ascorbic acid)", "ascorbic acid", "Vitamin (water-soluble)", "Essential nutrient; antioxidant. Decreases with storage and cooking.", r"vitamin.?c|ascorbic", None),
    "citric_acid": ("Citric acid", "citric acid", "Organic acid", "Main source of sourness in citrus fruits; also present in tomato.", None, None),
    "malic_acid": ("Malic acid", "malic acid", "Organic acid", "Main acid responsible for the tartness of apples.", None, None),
    "tartaric_acid": ("Tartaric acid", "tartaric acid", "Organic acid", "Characteristic acid of grapes.", None, None),
    "fructose": ("Fructose", "fructose", "Natural sugar (monosaccharide)", "Contributes sweetness; naturally present in fruit.", r"^fructose", None),
    "glucose": ("Glucose", "glucose", "Natural sugar (monosaccharide)", "Naturally present sugar; energy source.", r"glucose|dextrose", None),
    "sucrose": ("Sucrose", "sucrose", "Natural sugar (disaccharide)", "Naturally present sugar in ripe fruit such as mango and banana.", r"^sucrose", None),
    "quercetin": ("Quercetin", "quercetin", "Flavonoid (flavonol)", "Plant polyphenol; in apples it is concentrated mainly in the peel.", None, "Mostly in the peel/outer layers."),
    "chlorogenic_acid": ("Chlorogenic acid", "chlorogenic acid", "Phenolic acid", "Common plant phenolic; takes part in enzymatic browning of cut apple and potato.", None, None),
    "isoamyl_acetate": ("Isoamyl acetate", "isoamyl acetate", "Aroma compound (ester)", "A key contributor to the characteristic aroma of ripe banana.", None, None),
    "hesperidin": ("Hesperidin", "hesperidin", "Flavonoid (flavanone glycoside)", "Characteristic citrus flavonoid, concentrated in the peel and pith.", None, "Mostly in peel and white pith."),
    "limonene": ("Limonene", "limonene", "Terpene (aroma compound)", "Main component of citrus peel oil; gives citrus aroma.", None, "Found mainly in the peel oil."),
    "mangiferin": ("Mangiferin", "mangiferin", "Xanthonoid (polyphenol)", "Polyphenol characteristic of mango; higher in peel and leaves than in pulp.", None, "Higher in peel than in pulp."),
    "resveratrol": ("Resveratrol", "resveratrol", "Stilbene (polyphenol)", "Present in grape skins in small and highly variable amounts.", None, "Mainly in the skin; amounts are small."),
    "anthocyanins": ("Cyanidin-3-glucoside (an anthocyanin)", "cyanidin 3-glucoside", "Anthocyanin pigment", "Red-purple pigments in dark grapes, berries and pomegranate.", None, "Varies strongly by variety."),
    "pelargonidin": ("Pelargonidin-3-glucoside", "pelargonidin 3-glucoside", "Anthocyanin pigment", "Main red pigment of strawberries.", None, None),
    "ellagic_acid": ("Ellagic acid", "ellagic acid", "Polyphenol", "Polyphenol found in strawberries and pomegranate.", None, None),
    "punicalagin": ("Punicalagin", "punicalagin", "Ellagitannin (polyphenol)", "Major polyphenol of pomegranate, especially the peel and juice.", None, None),
    "solanine": ("Alpha-solanine", "alpha-solanine", "Glycoalkaloid (natural toxicant)", "Natural defence compound in potatoes; higher in green or sprouted parts.", None,
                 "Higher in green skin and sprouts; remove those parts."),
    "capsaicin": ("Capsaicin", "capsaicin", "Alkaloid (pungent compound)", "Causes the heat of chilli peppers.", None, None),
    "allicin": ("Allicin", "allicin", "Organosulfur compound", "Forms when garlic is crushed or chopped; responsible for its pungent smell.", None, "Formed on crushing; not present in intact cloves."),
    "propanethial": ("Syn-propanethial-S-oxide", "syn-propanethial S-oxide", "Organosulfur compound", "The tear-inducing compound released when onions are cut.", None, "Formed when the onion is cut."),
    "sulforaphane": ("Sulforaphane", "sulforaphane", "Isothiocyanate", "Formed from glucoraphanin when broccoli is chopped or chewed.", None, None),
    "lutein": ("Lutein", "lutein", "Carotenoid (xanthophyll)", "Yellow pigment in leafy greens and egg yolk.", r"lutein", None),
    "oxalic_acid": ("Oxalic acid", "oxalic acid", "Organic acid", "Naturally high in spinach; binds calcium.", None, None),
    "caffeine": ("Caffeine", "caffeine", "Alkaloid (stimulant)", "Natural stimulant in coffee and tea.", r"caffeine", None),
    "theobromine": ("Theobromine", "theobromine", "Alkaloid", "Main alkaloid in cocoa and chocolate.", r"theobromine", None),
    "egcg": ("Epigallocatechin gallate", "epigallocatechin gallate", "Catechin (polyphenol)", "Main catechin of green tea.", None, None),
    "lactose": ("Lactose", "lactose", "Natural sugar (disaccharide)", "The natural sugar of milk.", r"lactose", None),
    "cholesterol": ("Cholesterol", "cholesterol", "Sterol", "Present in animal foods such as egg yolk.", r"cholesterol", None),
    "citrulline": ("L-Citrulline", "citrulline", "Amino acid (non-protein)", "Amino acid found notably in watermelon.", None, None),
    "acrylamide": ("Acrylamide", "acrylamide", "Process contaminant", "Can form in starchy foods fried, baked or roasted at high temperature; "
                   "levels depend on cooking and cannot be seen in a photo.", None, "Not present in raw food; depends on cooking."),
    "piperine": ("Piperine", "piperine", "Alkaloid", "Pungent compound of black pepper.", None, None),
    "curcumin": ("Curcumin", "curcumin", "Curcuminoid pigment", "Yellow pigment of turmeric, common in Indian dishes.", None, "Only if turmeric was used."),
}

# keyword regex (matched against the lower-case food name) -> compound ids
FOODS: list[tuple[str, list[str]]] = [
    (r"tomato", ["lycopene", "beta_carotene", "ascorbic_acid", "citric_acid"]),
    (r"apple", ["malic_acid", "fructose", "quercetin", "chlorogenic_acid", "ascorbic_acid"]),
    (r"banana", ["sucrose", "glucose", "fructose", "isoamyl_acetate"]),
    (r"orange|mosambi|sweet lime", ["ascorbic_acid", "citric_acid", "hesperidin", "limonene"]),
    (r"lemon|lime", ["citric_acid", "ascorbic_acid", "limonene", "hesperidin"]),
    (r"mango", ["sucrose", "fructose", "beta_carotene", "mangiferin", "ascorbic_acid"]),
    (r"grape", ["glucose", "fructose", "tartaric_acid", "resveratrol", "anthocyanins"]),
    (r"strawberr", ["ascorbic_acid", "pelargonidin", "ellagic_acid", "fructose"]),
    (r"pomegranate", ["punicalagin", "ellagic_acid", "anthocyanins"]),
    (r"watermelon", ["lycopene", "citrulline", "fructose"]),
    (r"guava", ["ascorbic_acid", "lycopene"]),
    (r"papaya", ["beta_carotene", "lycopene", "ascorbic_acid"]),
    (r"pineapple", ["ascorbic_acid", "sucrose", "citric_acid"]),
    (r"potato|fries|chips", ["chlorogenic_acid", "solanine", "ascorbic_acid"]),
    (r"fries|chips|crisps", ["acrylamide"]),
    (r"carrot", ["beta_carotene", "alpha_carotene"]),
    (r"onion", ["quercetin", "propanethial"]),
    (r"garlic", ["allicin"]),
    (r"chil+i|jalape|green chil", ["capsaicin", "ascorbic_acid"]),
    (r"bell pepper|capsicum", ["ascorbic_acid", "beta_carotene"]),
    (r"black pepper", ["piperine"]),
    (r"broccoli", ["sulforaphane", "ascorbic_acid", "lutein"]),
    (r"spinach|palak", ["lutein", "oxalic_acid", "beta_carotene"]),
    (r"coffee", ["caffeine", "chlorogenic_acid"]),
    (r"\btea\b", ["caffeine", "egcg"]),
    (r"chocolate|cocoa", ["theobromine", "caffeine"]),
    (r"milk|paneer|curd|yog", ["lactose"]),
    (r"\beggs?\b|omelet", ["cholesterol", "lutein"]),
    (r"pizza|pasta|ketchup", ["lycopene"]),
    (r"curry|dal|biryani|sambar", ["curcumin", "piperine"]),
]


def compounds_for(food: str) -> list[dict]:
    import re  # noqa: PLC0415
    name = food.lower()
    ids: list[str] = []
    for pat, cids in FOODS:
        if re.search(pat, name):
            ids += [c for c in cids if c not in ids]
    out = []
    for cid in ids:
        common, query, category, role, usda_re, where = C[cid]
        out.append({"id": cid, "common_name": common, "pubchem_query": query, "category": category, "role": role,
                    "usda_nutrient_pattern": usda_re, "where": where})
    return out
