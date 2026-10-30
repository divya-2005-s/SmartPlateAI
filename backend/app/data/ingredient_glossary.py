"""Curated plain-language glossary of common packaged-food ingredients, additive classes and a few food-science topics.

Used by "Ingredients explained" (app/services/ingredients_explain.py) and as reference data for the chatbot.

Scope and rules:
- Textbook-level, well-documented facts only: what the ingredient is, its usual technological function, and points a
  consumer may want to know. INS numbers follow Codex "Class Names and the International Numbering System for Food
  Additives" (CAC/GL 36-1989).
- NO amounts, acceptable daily intakes, legal maximum levels or toxicity values. A listed "consider" point is never a
  verdict that the ingredient is safe or unsafe: effects depend on amount, frequency, the rest of the diet and the person.
- Specific regulatory statements name the rule they come from (e.g. the EU colour warning, the PKU warning for aspartame).
Each entry: key -> dict(name, aliases, ins, category, what, why, consider, source)
"""
from __future__ import annotations

CODEX_INS = "Codex Alimentarius CAC/GL 36-1989 (INS numbering)"
GLOSSARY_SOURCE = "SmartPlateAI curated ingredient glossary (general information)"
EU_AZO = ("In the EU, foods containing this colour must carry the statement \"may have an adverse effect on activity and attention "
          "in children\" (Regulation (EC) No 1333/2008, Annex V). Other countries, including India, permit it within set limits "
          "without this statement.")

ENTRIES: dict[str, dict] = {
    # ---------------------------------------------------------------- acids and acidity regulators
    "citric_acid": dict(name="Citric acid", aliases=["citric acid"], ins="330", category="Acidity regulator",
                        what="An organic acid that occurs naturally in citrus fruits such as lemons and oranges. The citric acid used "
                             "in food is usually made by fermentation.",
                        why="Adds a sour taste, controls acidity and helps other antioxidants keep food from going stale.",
                        consider="It is the same compound found in fruit. Very acidic foods and drinks in general can wear tooth enamel "
                                 "when consumed often.", source=CODEX_INS),
    "acetic_acid": dict(name="Acetic acid", aliases=["acetic acid"], ins="260", category="Acidity regulator",
                        what="The main acid in vinegar.", why="Adds sourness and helps preserve foods such as pickles and sauces.",
                        consider="Familiar from vinegar; used for taste and preservation.", source=CODEX_INS),
    "lactic_acid": dict(name="Lactic acid", aliases=["lactic acid"], ins="270", category="Acidity regulator",
                        what="An acid produced when bacteria ferment sugars; it occurs naturally in yogurt, curd and fermented vegetables.",
                        why="Adds a mild sour taste and controls acidity.", consider="Despite the name, it is not made from milk in "
                        "most foods and is not a milk allergen.", source=CODEX_INS),
    "malic_acid": dict(name="Malic acid", aliases=["malic acid"], ins="296", category="Acidity regulator",
                       what="An organic acid that gives apples much of their tartness.", why="Adds a sharp fruity sourness, often in "
                       "sweets and drinks.", consider="Occurs naturally in many fruits.", source=CODEX_INS),
    "sodium_citrate": dict(name="Sodium citrates", aliases=["sodium citrate", "trisodium citrate"], ins="331", category="Acidity regulator",
                           what="Sodium salts of citric acid.", why="Controls acidity and helps processed cheese melt smoothly.",
                           consider="Contributes a small amount of sodium.", source=CODEX_INS),
    # ---------------------------------------------------------------- antioxidants and vitamins
    "ascorbic_acid": dict(name="Ascorbic acid (vitamin C)", aliases=["ascorbic acid", "l-ascorbic acid", "vitamin c"], ins="300",
                          category="Antioxidant / vitamin",
                          what="Another name for vitamin C.",
                          why="Stops fats and colours from reacting with oxygen, keeps cut fruit from browning, and improves bread dough; "
                              "it may also be added to raise the vitamin C content.",
                          consider="As an additive it is used in small amounts; it does not make a product a significant vitamin source "
                                   "unless the nutrition panel says so.", source=CODEX_INS),
    "sodium_ascorbate": dict(name="Sodium ascorbate", aliases=["sodium ascorbate"], ins="301", category="Antioxidant",
                             what="The sodium salt of vitamin C.", why="Antioxidant; often used in cured meats together with nitrite.",
                             consider="A form of vitamin C.", source=CODEX_INS),
    "tocopherols": dict(name="Tocopherols (vitamin E)", aliases=["tocopherol", "tocopherols", "mixed tocopherols", "vitamin e"], ins="306",
                        category="Antioxidant", what="Forms of vitamin E, often extracted from vegetable oils.",
                        why="Slow down fats and oils going rancid.", consider="Natural antioxidants also found in nuts and seeds.",
                        source=CODEX_INS),
    "tbhq": dict(name="TBHQ (tertiary butylhydroquinone)", aliases=["tbhq", "tertiary butylhydroquinone", "tert-butylhydroquinone"],
                 ins="319", category="Antioxidant", what="A synthetic antioxidant.", why="Slows rancidity in oils, fried snacks and "
                 "instant noodles.", consider="Permitted only within limits set by food regulators.", source=CODEX_INS),
    "bha": dict(name="BHA (butylated hydroxyanisole)", aliases=["bha", "butylated hydroxyanisole"], ins="320", category="Antioxidant",
                what="A synthetic antioxidant.", why="Slows rancidity in fats and fatty foods.", consider="Permitted only within limits "
                "set by food regulators.", source=CODEX_INS),
    "bht": dict(name="BHT (butylated hydroxytoluene)", aliases=["bht", "butylated hydroxytoluene"], ins="321", category="Antioxidant",
                what="A synthetic antioxidant.", why="Slows rancidity in fats and fatty foods.", consider="Permitted only within limits "
                "set by food regulators.", source=CODEX_INS),
    # ---------------------------------------------------------------- emulsifiers, stabilisers, thickeners
    "lecithin": dict(name="Lecithins", aliases=["lecithin", "lecithins", "soy lecithin", "soya lecithin", "sunflower lecithin"], ins="322",
                     category="Emulsifier",
                     what="Natural fat-like substances (phospholipids), usually taken from soybeans or sunflower seeds, sometimes egg.",
                     why="Helps ingredients that normally separate, such as oil and water, stay mixed (for example in chocolate and "
                         "spreads).",
                     consider="Lecithin from soy or egg is relevant if you are allergic to those foods; the label should say the source.",
                     source=CODEX_INS),
    "mono_diglycerides": dict(name="Mono- and diglycerides of fatty acids",
                              aliases=["mono- and diglycerides", "mono and diglycerides", "mono and di-glycerides",
                                       "mono- and di-glycerides of fatty acids", "monoglycerides"],
                              ins="471", category="Emulsifier", what="Emulsifiers made from fats and glycerol.",
                              why="Keep bread soft, improve texture and stop oil separating.",
                              consider="The fat source (plant or animal) is not always stated; this can matter for some diets.",
                              source=CODEX_INS),
    "ssl": dict(name="Sodium stearoyl lactylate", aliases=["sodium stearoyl lactylate", "sodium stearoyl-2-lactylate"], ins="481",
                category="Emulsifier", what="An emulsifier made from a fatty acid and lactic acid.",
                why="Strengthens dough and keeps baked goods soft.", consider="Commonly used in bread and buns.", source=CODEX_INS),
    "carrageenan": dict(name="Carrageenan", aliases=["carrageenan"], ins="407", category="Thickener / gelling agent",
                        what="A substance extracted from red seaweed.", why="Thickens and stabilises dairy drinks, desserts and sauces.",
                        consider="Permitted as a food additive; some people choose to limit it.", source=CODEX_INS),
    "locust_bean_gum": dict(name="Locust bean gum", aliases=["locust bean gum", "carob bean gum"], ins="410",
                            category="Thickener / stabiliser", what="A gum from the seeds of the carob tree.",
                            why="Thickens and stabilises ice cream and sauces.", consider="A plant-based fibre-like substance.",
                            source=CODEX_INS),
    "guar_gum": dict(name="Guar gum", aliases=["guar gum"], ins="412", category="Thickener / stabiliser",
                     what="A gum made from guar beans.", why="Thickens sauces, dairy products and gluten-free baking.",
                     consider="A soluble fibre; large amounts can cause bloating in some people.", source=CODEX_INS),
    "gum_arabic": dict(name="Gum arabic (acacia gum)", aliases=["gum arabic", "acacia gum", "gum acacia"], ins="414",
                       category="Thickener / stabiliser", what="A natural gum from acacia trees.",
                       why="Stabilises drinks and coatings and keeps flavours evenly mixed.", consider="A plant gum.", source=CODEX_INS),
    "xanthan_gum": dict(name="Xanthan gum", aliases=["xanthan gum", "xanthan"], ins="415", category="Thickener / stabiliser",
                        what="A thickener made by fermenting sugar with bacteria.",
                        why="Keeps sauces and dressings thick and stops ingredients separating.",
                        consider="Used in small amounts.", source=CODEX_INS),
    "pectin": dict(name="Pectin", aliases=["pectin", "pectins"], ins="440", category="Gelling agent",
                   what="A natural fibre found in fruit, especially apples and citrus peel.", why="Sets jams and jellies.",
                   consider="Occurs naturally in fruit.", source=CODEX_INS),
    "cmc": dict(name="Sodium carboxymethyl cellulose", aliases=["carboxymethyl cellulose", "sodium carboxymethyl cellulose", "cmc"],
                ins="466", category="Thickener / stabiliser", what="A thickener made from plant cellulose.",
                why="Gives body to ice cream, sauces and drinks.", consider="Not digested like starch; used in small amounts.",
                source=CODEX_INS),
    "modified_starch": dict(name="Modified starch", aliases=["modified starch", "modified starches", "modified corn starch",
                                                              "modified maize starch", "modified tapioca starch"],
                            ins=None, category="Thickener",
                            what="Starch (from maize, tapioca, potato or wheat) treated so it behaves better in cooking and storage. "
                                 "Specific types have INS numbers between 1400 and 1450.",
                            why="Thickens sauces, soups and fillings and keeps them stable when heated or frozen.",
                            consider="\"Modified\" refers to physical or chemical treatment of the starch, not genetic modification. "
                                     "Wheat-based starch may matter for people avoiding gluten.", source=CODEX_INS),
    # ---------------------------------------------------------------- preservatives
    "sodium_benzoate": dict(name="Sodium benzoate", aliases=["sodium benzoate"], ins="211", category="Preservative",
                            what="The sodium salt of benzoic acid. Benzoic acid also occurs naturally in small amounts in some berries "
                                 "and spices.",
                            why="Limits the growth of yeasts, moulds and some bacteria, mainly in acidic foods such as soft drinks, "
                                "pickles and sauces.",
                            consider="Permitted within limits set by food regulators. A small number of people are sensitive to "
                                     "benzoates.", source=CODEX_INS),
    "sorbic_acid": dict(name="Sorbic acid", aliases=["sorbic acid"], ins="200", category="Preservative",
                        what="An organic acid first found in rowan berries.", why="Prevents mould and yeast growth.",
                        consider="Permitted within limits set by food regulators.", source=CODEX_INS),
    "potassium_sorbate": dict(name="Potassium sorbate", aliases=["potassium sorbate"], ins="202", category="Preservative",
                              what="The potassium salt of sorbic acid.", why="Prevents mould and yeast growth in cheese, baked goods, "
                              "sauces and drinks.", consider="Permitted within limits set by food regulators.", source=CODEX_INS),
    "sulphites": dict(name="Sodium metabisulphite (a sulphite)", aliases=["sodium metabisulphite", "sodium metabisulfite",
                                                                          "sulphite", "sulphites", "sulfite", "sulfites"],
                      ins="223", category="Preservative / antioxidant",
                      what="A sulphur-based preservative.", why="Prevents browning and microbial spoilage in dried fruit, some drinks "
                      "and batters.",
                      consider="Sulphites can trigger reactions in some people, particularly some people with asthma. Codex labelling "
                               "rules require sulphites at 10 mg/kg or more to be declared.", source=CODEX_INS),
    "sodium_nitrite": dict(name="Sodium nitrite", aliases=["sodium nitrite"], ins="250", category="Preservative",
                           what="A salt used in curing meat.", why="Helps prevent the growth of Clostridium botulinum in cured meats "
                           "and gives them their pink colour.", consider="Its use is limited by food regulations. It is found mainly "
                           "in processed and cured meats.", source=CODEX_INS),
    # ---------------------------------------------------------------- colours
    "curcumin": dict(name="Curcumin", aliases=["curcumin", "turmeric extract"], ins="100", category="Colour",
                     what="The yellow pigment of turmeric.", why="Gives a yellow colour.", consider="A colour of natural origin.",
                     source=CODEX_INS),
    "tartrazine": dict(name="Tartrazine", aliases=["tartrazine"], ins="102", category="Colour (synthetic)",
                       what="A synthetic yellow azo dye.", why="Gives a bright yellow colour.", consider=EU_AZO,
                       source=CODEX_INS + "; EU Regulation (EC) No 1333/2008"),
    "sunset_yellow": dict(name="Sunset Yellow FCF", aliases=["sunset yellow", "sunset yellow fcf"], ins="110", category="Colour (synthetic)",
                          what="A synthetic orange-yellow azo dye.", why="Gives an orange colour.", consider=EU_AZO,
                          source=CODEX_INS + "; EU Regulation (EC) No 1333/2008"),
    "carmoisine": dict(name="Carmoisine (azorubine)", aliases=["carmoisine", "azorubine"], ins="122", category="Colour (synthetic)",
                       what="A synthetic red azo dye.", why="Gives a red colour.", consider=EU_AZO,
                       source=CODEX_INS + "; EU Regulation (EC) No 1333/2008"),
    "ponceau_4r": dict(name="Ponceau 4R", aliases=["ponceau 4r", "ponceau"], ins="124", category="Colour (synthetic)",
                       what="A synthetic red azo dye.", why="Gives a red colour.", consider=EU_AZO,
                       source=CODEX_INS + "; EU Regulation (EC) No 1333/2008"),
    "allura_red": dict(name="Allura Red AC", aliases=["allura red", "allura red ac"], ins="129", category="Colour (synthetic)",
                       what="A synthetic red azo dye.", why="Gives a red colour.", consider=EU_AZO,
                       source=CODEX_INS + "; EU Regulation (EC) No 1333/2008"),
    "caramel": dict(name="Caramel colour", aliases=["caramel colour", "caramel color"], ins="150", category="Colour",
                    what="Brown colours made by heating sugars; there are four classes (150a to 150d), made with or without "
                         "additional reactants.", why="Gives a brown colour to colas, sauces and baked goods.",
                    consider="The label may name the class (for example 150c or 150d).", source=CODEX_INS),
    "beta_carotene": dict(name="Beta-carotene", aliases=["beta-carotene", "beta carotene"], ins="160a", category="Colour",
                          what="An orange pigment found in carrots and other plants.", why="Gives a yellow-orange colour.",
                          consider="The body can convert it to vitamin A.", source=CODEX_INS),
    "annatto": dict(name="Annatto", aliases=["annatto", "bixin", "norbixin"], ins="160b", category="Colour",
                    what="An orange-yellow colour from the seeds of the achiote tree.", why="Colours cheese, butter and snacks.",
                    consider="A colour of natural origin.", source=CODEX_INS),
    "paprika_extract": dict(name="Paprika extract", aliases=["paprika extract", "paprika oleoresin", "capsanthin"], ins="160c",
                            category="Colour", what="A red-orange colour extracted from paprika peppers.", why="Gives a red-orange colour.",
                            consider="A colour of natural origin.", source=CODEX_INS),
    # ---------------------------------------------------------------- flavour enhancers
    "msg": dict(name="Monosodium glutamate (MSG)", aliases=["monosodium glutamate", "msg", "monosodium l-glutamate"], ins="621",
                category="Flavour enhancer",
                what="The sodium salt of glutamic acid, an amino acid. Glutamate also occurs naturally in foods such as tomatoes, "
                     "cheese and mushrooms.",
                why="Gives a savoury (umami) taste.",
                consider="Regulators permit it as a food additive. It contains sodium, so it adds to total sodium intake.",
                source=CODEX_INS),
    "disodium_guanylate": dict(name="Disodium guanylate", aliases=["disodium guanylate", "disodium 5'-guanylate"], ins="627",
                               category="Flavour enhancer", what="A flavour enhancer related to compounds found in mushrooms and fish.",
                               why="Strengthens savoury taste, usually together with MSG.", consider="Contains sodium.",
                               source=CODEX_INS),
    "disodium_inosinate": dict(name="Disodium inosinate", aliases=["disodium inosinate", "disodium 5'-inosinate"], ins="631",
                               category="Flavour enhancer", what="A flavour enhancer related to compounds found in meat and fish.",
                               why="Strengthens savoury taste, usually together with MSG.", consider="Contains sodium. It is often "
                               "made from animal or fish sources, which can matter for vegetarians.", source=CODEX_INS),
    "ribonucleotides": dict(name="Disodium 5'-ribonucleotides", aliases=["disodium 5'-ribonucleotides", "disodium ribonucleotides",
                                                                          "ribonucleotides"],
                            ins="635", category="Flavour enhancer", what="A mixture of disodium inosinate and disodium guanylate.",
                            why="Strengthens savoury taste.", consider="Contains sodium.", source=CODEX_INS),
    # ---------------------------------------------------------------- raising agents, anticaking, firming
    "sodium_bicarbonate": dict(name="Sodium bicarbonate (baking soda)", aliases=["sodium bicarbonate", "sodium hydrogen carbonate",
                                                                                 "baking soda"],
                               ins="500", category="Raising agent",
                               what="Baking soda. INS 500(ii) is sodium hydrogen carbonate.",
                               why="Releases carbon dioxide when heated or mixed with acid, which makes batters and doughs rise.",
                               consider="Contains sodium.", source=CODEX_INS),
    "ammonium_bicarbonate": dict(name="Ammonium bicarbonate", aliases=["ammonium bicarbonate", "ammonium hydrogen carbonate"], ins="503",
                                 category="Raising agent", what="A traditional raising agent.",
                                 why="Makes biscuits and crackers light and crisp; it breaks down into gases during baking.",
                                 consider="Little of it remains in the finished baked product.", source=CODEX_INS),
    "phosphates": dict(name="Phosphates", aliases=["diphosphates", "sodium phosphate", "sodium phosphates", "triphosphates",
                                                   "polyphosphates", "sodium acid pyrophosphate"],
                       ins="450", category="Raising agent / emulsifying salt",
                       what="Salts of phosphoric acid. INS 450 covers diphosphates; 339 covers sodium phosphates.",
                       why="Act as raising agents, help processed cheese and meats hold water and texture.",
                       consider="They add phosphorus to the diet.", source=CODEX_INS),
    "calcium_carbonate": dict(name="Calcium carbonate", aliases=["calcium carbonate"], ins="170",
                              category="Anticaking agent / colour / calcium source",
                              what="A natural mineral (the main component of chalk and eggshell).",
                              why="Stops powders from clumping, adds white colour, or adds calcium.", consider="A source of calcium.",
                              source=CODEX_INS),
    "silicon_dioxide": dict(name="Silicon dioxide", aliases=["silicon dioxide", "silica"], ins="551", category="Anticaking agent",
                            what="A mineral compound (silica).", why="Keeps powders such as spice mixes and salt free-flowing.",
                            consider="Used in small amounts.", source=CODEX_INS),
    # ---------------------------------------------------------------- glazing agents (fruit coatings)
    "beeswax": dict(name="Beeswax", aliases=["beeswax"], ins="901", category="Glazing agent",
                    what="Wax made by honeybees.", why="Used as a coating or glaze on some sweets and fruit.",
                    consider="An animal-derived ingredient, which can matter for vegans.", source=CODEX_INS),
    "carnauba_wax": dict(name="Carnauba wax", aliases=["carnauba wax", "carnauba"], ins="903", category="Glazing agent",
                         what="A plant wax from the leaves of the carnauba palm.",
                         why="Gives a shiny coating to sweets and is used in some approved coatings for fruit.",
                         consider="Plant-derived and used in thin layers.", source=CODEX_INS),
    "shellac": dict(name="Shellac", aliases=["shellac"], ins="904", category="Glazing agent",
                    what="A resin produced by the lac insect.", why="Gives a glossy coating to sweets and is used in some approved "
                    "coatings for fruit.", consider="An insect-derived ingredient, which can matter for vegans.", source=CODEX_INS),
    # ---------------------------------------------------------------- sweeteners
    "aspartame": dict(name="Aspartame", aliases=["aspartame"], ins="951", category="Sweetener (low-calorie)",
                      what="A low-calorie sweetener made from two amino acids, one of which is phenylalanine.",
                      why="Gives sweetness with very few calories.",
                      consider="Labelling rules (for example FSSAI and EU rules) require a warning that it contains phenylalanine, "
                               "which people with the inherited condition phenylketonuria (PKU) must avoid. Regulators permit it within "
                               "set limits.", source=CODEX_INS),
    "acesulfame_k": dict(name="Acesulfame potassium", aliases=["acesulfame potassium", "acesulfame k", "acesulfame-k"], ins="950",
                         category="Sweetener (low-calorie)", what="A calorie-free sweetener.", why="Gives sweetness, often combined "
                         "with other sweeteners.", consider="Permitted within limits set by food regulators.", source=CODEX_INS),
    "sucralose": dict(name="Sucralose", aliases=["sucralose"], ins="955", category="Sweetener (low-calorie)",
                      what="A calorie-free sweetener made from sugar.", why="Gives sweetness with almost no calories.",
                      consider="Permitted within limits set by food regulators.", source=CODEX_INS),
    "steviol_glycosides": dict(name="Steviol glycosides (stevia)", aliases=["steviol glycosides", "stevia", "stevia extract"], ins="960",
                               category="Sweetener (low-calorie)", what="Sweet compounds extracted from the leaves of the stevia plant.",
                               why="Gives sweetness with almost no calories.", consider="Can have a slightly bitter aftertaste.",
                               source=CODEX_INS),
    "sorbitol": dict(name="Sorbitol", aliases=["sorbitol"], ins="420", category="Sweetener / humectant",
                     what="A sugar alcohol found naturally in some fruits.", why="Adds sweetness and keeps foods moist; common in "
                     "sugar-free sweets.", consider="Eating large amounts can have a laxative effect.", source=CODEX_INS),
    # ---------------------------------------------------------------- common ingredients (not additives)
    "salt": dict(name="Salt", aliases=["salt", "iodised salt", "iodized salt", "common salt", "sodium chloride", "rock salt"], ins=None,
                 category="Ingredient (seasoning)",
                 what="Sodium chloride. Iodised salt has iodine added.", why="Adds flavour and helps preserve food.",
                 consider="Salt is the main source of sodium in most diets; the sodium value on the nutrition panel shows how much "
                          "the product contains.", source=GLOSSARY_SOURCE),
    "sugar": dict(name="Sugar", aliases=["sugar", "sucrose", "cane sugar", "refined sugar"], ins=None, category="Ingredient (sweetener)",
                  what="Sucrose, usually from sugar cane or sugar beet.", why="Adds sweetness, browning and texture, and helps preserve "
                  "jams.", consider="Sugar added during manufacture counts as added sugar. The nutrition panel shows total sugars "
                  "per 100 g or per serving.", source=GLOSSARY_SOURCE),
    "glucose_syrup": dict(name="Glucose syrup", aliases=["glucose syrup", "liquid glucose", "corn syrup"], ins=None,
                          category="Ingredient (sweetener)", what="A syrup made by breaking down starch.",
                          why="Adds sweetness and keeps sweets soft and smooth.", consider="Counts as added sugar.",
                          source=GLOSSARY_SOURCE),
    "invert_sugar": dict(name="Invert sugar syrup", aliases=["invert sugar", "invert sugar syrup", "invert syrup"], ins=None,
                         category="Ingredient (sweetener)", what="Sugar syrup split into glucose and fructose.",
                         why="Adds sweetness and keeps baked goods moist.", consider="Counts as added sugar.", source=GLOSSARY_SOURCE),
    "maltodextrin": dict(name="Maltodextrin", aliases=["maltodextrin"], ins=None, category="Ingredient (carbohydrate)",
                         what="A carbohydrate powder made from starch (often maize, rice or potato).",
                         why="Adds body, carries flavours and improves texture.",
                         consider="It is digested like starch and provides energy.", source=GLOSSARY_SOURCE),
    "palm_oil": dict(name="Palm oil", aliases=["palm oil", "palmolein", "palmolein oil", "palm kernel oil", "refined palmolein"],
                     ins=None, category="Ingredient (fat)",
                     what="A vegetable oil from the fruit (palm oil, palmolein) or seed (palm kernel oil) of the oil palm.",
                     why="Gives crispness and a long shelf life to fried snacks, biscuits and spreads.",
                     consider="It contains a higher share of saturated fat than most other vegetable oils; the saturated fat value "
                              "on the nutrition panel shows how much the product contains.", source=GLOSSARY_SOURCE),
    "hydrogenated_oil": dict(name="Hydrogenated vegetable oil", aliases=["hydrogenated vegetable oil", "hydrogenated oil",
                                                                         "partially hydrogenated", "vanaspati", "hydrogenated vegetable fat"],
                             ins=None, category="Ingredient (fat)",
                             what="Vegetable oil hardened by hydrogenation. Vanaspati is a hydrogenated vegetable fat.",
                             why="Makes fats solid at room temperature for baking and frying.",
                             consider="Partially hydrogenated oils can contain trans fats; the trans fat value on the nutrition panel, "
                                      "when given, shows how much the product contains.", source=GLOSSARY_SOURCE),
    "vegetable_oil": dict(name="Edible vegetable oil", aliases=["edible vegetable oil", "vegetable oil", "refined vegetable oil",
                                                                "sunflower oil", "rice bran oil", "groundnut oil", "soybean oil", "mustard oil"],
                          ins=None, category="Ingredient (fat)", what="Oil pressed or extracted from seeds, nuts or fruits.",
                          why="Used for frying, texture and flavour.",
                          consider="\"Edible vegetable oil\" alone does not say which oil was used; this matters for fat type and "
                                   "for allergies (for example groundnut/peanut oil).", source=GLOSSARY_SOURCE),
    "refined_wheat_flour": dict(name="Refined wheat flour (maida)", aliases=["refined wheat flour", "maida", "wheat flour (maida)"],
                                ins=None, category="Ingredient (cereal)",
                                what="Wheat flour with most of the bran and germ removed.", why="Gives a soft, light texture.",
                                consider="Contains gluten (wheat). It has less fibre than whole wheat flour (atta).",
                                source=GLOSSARY_SOURCE),
    "whole_wheat_flour": dict(name="Whole wheat flour (atta)", aliases=["whole wheat flour", "atta", "wholemeal flour"], ins=None,
                              category="Ingredient (cereal)", what="Flour milled from the whole wheat grain, including bran.",
                              why="Main ingredient of chapati and many breads.", consider="Contains gluten (wheat) and more fibre "
                              "than refined flour.", source=GLOSSARY_SOURCE),
    "milk_solids": dict(name="Milk solids", aliases=["milk solids", "milk powder", "skimmed milk powder", "whole milk powder",
                                                     "milk solids non-fat"],
                        ins=None, category="Ingredient (dairy)", what="The parts of milk left after removing the water.",
                        why="Add creaminess, flavour and protein.", consider="A milk allergen; also contains lactose.",
                        source=GLOSSARY_SOURCE),
    "yeast_extract": dict(name="Yeast extract", aliases=["yeast extract"], ins=None, category="Ingredient (flavouring)",
                          what="The contents of yeast cells, concentrated.", why="Adds a savoury taste.",
                          consider="It contains naturally occurring glutamates and usually some salt.", source=GLOSSARY_SOURCE),
    "flavouring": dict(name="Flavourings", aliases=["natural flavouring", "natural flavour", "nature identical flavouring substances",
                                                    "artificial flavouring substances", "added flavours", "added flavour", "flavouring substances",
                                                    "flavouring", "flavourings", "flavoring"],
                       ins=None, category="Flavouring",
                       what="Substances that give or strengthen a taste or smell. Labels in India use terms such as natural, "
                            "nature-identical and artificial flavouring substances.",
                       why="Give the product its intended flavour.",
                       consider="The individual flavouring substances are usually not listed.", source=GLOSSARY_SOURCE),
}

# Additive class names as printed on labels ("Acidity regulator (330)") -> plain explanation of the function.
CLASSES: dict[str, str] = {
    "acidity regulator": "Controls how acidic or alkaline the food is, which affects taste, safety and texture.",
    "acidulant": "Adds sourness or controls acidity.",
    "antioxidant": "Slows down reactions with oxygen that make fats rancid or change colour.",
    "emulsifier": "Helps ingredients that normally separate, such as oil and water, stay mixed.",
    "stabiliser": "Keeps the texture and mixture of a food stable over time.",
    "stabilizer": "Keeps the texture and mixture of a food stable over time.",
    "thickener": "Makes liquids thicker.",
    "gelling agent": "Makes a food set into a gel, as in jams and jellies.",
    "preservative": "Limits the growth of microorganisms such as moulds, yeasts or bacteria, so food keeps longer.",
    "colour": "Adds or restores colour.",
    "color": "Adds or restores colour.",
    "flavour enhancer": "Strengthens the existing taste of a food, usually a savoury taste.",
    "flavor enhancer": "Strengthens the existing taste of a food, usually a savoury taste.",
    "raising agent": "Releases gas so that dough or batter rises.",
    "leavening agent": "Releases gas so that dough or batter rises.",
    "sweetener": "Gives a sweet taste.",
    "anticaking agent": "Stops powders and granules from sticking together.",
    "anti-caking agent": "Stops powders and granules from sticking together.",
    "humectant": "Keeps food from drying out.",
    "glazing agent": "Gives a shiny coating or protective layer.",
    "flour treatment agent": "Improves how flour behaves in baking.",
    "emulsifying salt": "Helps proteins and fats in processed cheese mix smoothly.",
    "firming agent": "Keeps fruit and vegetables firm or crisp.",
}

# Food-science topics the chatbot often gets asked about. Matched by keywords in the question.
TOPICS: dict[str, dict] = {
    "fruit_wax": dict(
        title="Wax on fruit (for example apples)",
        keywords=["wax", "waxed", "waxy", "coating", "coated", "shiny", "shine", "glossy"],
        points=[
            "Apples and some other fruit naturally produce a thin waxy layer (the cuticle) on their skin that reduces water loss.",
            "Washing and brushing after harvest removes some of that natural wax, so packers may apply a thin approved coating, "
            "such as carnauba wax (INS 903) or shellac (INS 904), to reduce moisture loss and restore shine. Whether a coating "
            "was used depends on the producer and the country's rules.",
            "A shiny appearance alone cannot show whether a fruit has an added coating: natural wax can also look shiny, "
            "especially after rubbing.",
            "Rinsing under running water while rubbing the surface gently helps remove dirt and some surface residues. It should "
            "not be assumed to remove every coating completely; peeling removes the skin, and with it some fibre and nutrients.",
            "Whether a particular fruit was coated can only be confirmed from the supplier, the store or the packaging.",
        ],
        related=["beeswax", "carnauba_wax", "shellac"],
        source="SmartPlateAI curated food-science notes; glazing agents per " + CODEX_INS,
    ),
}
