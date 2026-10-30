# SmartPlateAI - Dataset Audit Report

Generated: 2026-10-10 23:14:17  
Script version: 1.0

## Key findings

- **[HIGH]** Split leakage: 1,582 test images (21.3%) have an augmented/original twin in train or validation (matched by filename family). Test accuracy on this split would be inflated. Phase 3 will build a group-aware split (your original CSV is left untouched).
- **[HIGH]** 1172 near-duplicate groups span splits; 752 test images have a near-duplicate in train/validation.
- **[HIGH]** 85% of packaged products have calcium=0 and iron=0 - almost certainly missing values stored as 0. Convert to 'not available' before showing them.
- **[HIGH]** 72 packaged rows have a serving size other than 100 g and the table has no basis column (per 100 g vs per serving). Per-serving and per-100 g values must never be mixed.
- **[HIGH]** 8 additive codes look malformed or unverifiable: INS 1500, INS 2021, INS 2620, INS 3076, INS 3310, INS 4221, INS 4500, INS 5330. Check them against the original ingredient text and the Codex INS list.
- **[HIGH]** Additive extraction is incomplete: 105 products have INS/E codes in the text that the table misses (+187 with codes written like 'EMULSIFIER [472e]' or 'RAISING AGENTS 503'; 289 products in total have at least one missed code). The extractor probably needs the word 'INS' and ignores the 'E' prefix and bare numbers after a function name. Full list: reports/additive_extraction_gaps.csv.
- **[HIGH]** 8 reference entries have codes that look malformed (INS 1500, INS 2021, INS 2620, INS 3076, INS 3310, INS 4221, INS 4500, INS 5330) yet carry specific additive names. Names for such codes may be wrong; verify each against Codex.
- **[MEDIUM]** Strong class imbalance (15.6x). Training needs class weights or balanced sampling, and the report must use macro-averaged metrics.
- **[MEDIUM]** Source confounding: 21 of 24 foods come from a single image source, so a model can partly learn the dataset's photo style instead of the food. Interpret test accuracy with care.
- **[MEDIUM]** 13,599 images are labelled condition=Unknown but their class name already says Fresh/Rotten. These can be used for the freshness model after you confirm the heuristic.
- **[MEDIUM]** 52 packaged rows have impossible/suspicious nutrient values (see packaged_food_flags.csv).
- **[MEDIUM]** Almost no provenance recorded (source/date/collector). You cannot trace where nutrient values came from, and the sources that are named may have terms-of-use limits.
- **[MEDIUM]** The additive reference cites organisations (Codex/JECFA/FSSAI) but no specific document, version or URL per entry, so none of its regulatory statements can be traced. Treat as UNVERIFIED until checked against the primary sources.
- **[MEDIUM]** Every reference code occurs in your 852 products and nothing else: the reference appears to be built only from observed codes. Any other INS code the OCR finds will have no entry (the app must say 'not in our reference').


## 1. Dataset discovery

Search depth limit: 4 folder levels. Only these roots were searched (your whole computer is never scanned):

| searched_root | exists |
| --- | --- |
| D:\SmartPlateAI | True |
| D:\Food_Composition_Project | True |

| dataset | status | path |
| --- | --- | --- |
| final_food_nutrient_dataset.csv | found | D:\Food_Composition_Project\output\final_food_nutrient_dataset.csv |
| packaged_foods_india_clean.csv | found | D:\Food_Composition_Project\output\packaged_foods_india_clean.csv |
| packaged_food_additives.csv | found | D:\Food_Composition_Project\output\packaged_food_additives.csv |
| additive_reference_populated.csv | found | D:\Food_Composition_Project\output\additive_reference_populated.csv |


## 2. Food image dataset (final_food_nutrient_dataset.csv)

Rows: **49,677**, columns: **37**.

Detected 28 nutrient columns (by unit suffix): energy_kcal, protein_g, fat_g, carbohydrate_g, fiber_g, sugars_g, calcium_mg, iron_mg, magnesium_mg, phosphorus_mg, potassium_mg, sodium_mg, zinc_mg, copper_mg, manganese_mg, selenium_ug, vitamin_a_rae_ug, vitamin_c_mg, vitamin_e_mg, vitamin_k_ug, thiamin_mg, riboflavin_mg, niacin_mg, vitamin_b6_mg, folate_dfe_ug, vitamin_b12_ug, vitamin_d_ug, water_g


### 2.1 Schema and missing values

| column | dtype | non_null | missing | missing_% | unique |
| --- | --- | --- | --- | --- | --- |
| image_id | int64 | 49677 | 0 | 0.0 | 49677 |
| image_name | str | 49677 | 0 | 0.0 | 46677 |
| image_path | str | 49677 | 0 | 0.0 | 49677 |
| food | str | 49677 | 0 | 0.0 | 24 |
| class | str | 49677 | 0 | 0.0 | 18 |
| condition | str | 49677 | 0 | 0.0 | 3 |
| source_dataset | str | 49677 | 0 | 0.0 | 3 |
| split | str | 49677 | 0 | 0.0 | 3 |
| fdc_id | int64 | 49677 | 0 | 0.0 | 24 |
| energy_kcal | float64 | 49677 | 0 | 0.0 | 24 |
| protein_g | float64 | 49677 | 0 | 0.0 | 24 |
| fat_g | float64 | 49677 | 0 | 0.0 | 22 |
| carbohydrate_g | float64 | 49677 | 0 | 0.0 | 24 |
| fiber_g | float64 | 49277 | 400 | 0.81 | 17 |
| sugars_g | float64 | 49277 | 400 | 0.81 | 23 |
| calcium_mg | float64 | 49677 | 0 | 0.0 | 19 |
| iron_mg | float64 | 49677 | 0 | 0.0 | 22 |
| magnesium_mg | float64 | 49677 | 0 | 0.0 | 15 |
| phosphorus_mg | float64 | 49677 | 0 | 0.0 | 20 |
| potassium_mg | float64 | 49677 | 0 | 0.0 | 24 |
| sodium_mg | float64 | 49677 | 0 | 0.0 | 17 |
| zinc_mg | float64 | 49677 | 0 | 0.0 | 23 |
| copper_mg | float64 | 49677 | 0 | 0.0 | 23 |
| manganese_mg | float64 | 49677 | 0 | 0.0 | 24 |
| selenium_ug | float64 | 49277 | 400 | 0.81 | 15 |
| vitamin_a_rae_ug | float64 | 49677 | 0 | 0.0 | 17 |
| vitamin_c_mg | float64 | 47748 | 1929 | 3.88 | 20 |
| vitamin_e_mg | float64 | 47348 | 2329 | 4.69 | 20 |
| vitamin_k_ug | float64 | 47348 | 2329 | 4.69 | 19 |
| thiamin_mg | float64 | 49677 | 0 | 0.0 | 23 |
| riboflavin_mg | float64 | 49677 | 0 | 0.0 | 22 |
| niacin_mg | float64 | 49677 | 0 | 0.0 | 24 |
| vitamin_b6_mg | float64 | 49677 | 0 | 0.0 | 24 |
| folate_dfe_ug | float64 | 45576 | 4101 | 8.26 | 20 |
| vitamin_b12_ug | float64 | 47905 | 1772 | 3.57 | 9 |
| vitamin_d_ug | float64 | 45576 | 4101 | 8.26 | 3 |
| water_g | float64 | 49677 | 0 | 0.0 | 24 |


### 2.2 Label hygiene

**food** - 24 distinct values; leading/trailing-space values: 0; empty/unknown-like values: 0; spelling/case collisions: 0

| food | count |
| --- | --- |
| Banana | 6235 |
| Apple | 6158 |
| Orange | 4950 |
| Mango | 3193 |
| Strawberry | 2581 |
| Donut | 1972 |
| Taco | 1971 |
| Pizza | 1964 |
| Sandwich | 1955 |
| Hot Dog | 1952 |
| Burger | 1938 |
| Crispy Chicken | 1929 |
| Taquito | 1893 |
| Baked Potato | 1834 |
| Fries | 1772 |
| Tomato | 1176 |
| Potato | 1174 |
| Cucumber | 1167 |
| Bell Pepper | 1147 |
| Carrot | 1116 |
| Grape | 400 |
| Guava | 400 |
| Jujube | 400 |
| Pomegranate | 400 |

**class** - 18 distinct values; leading/trailing-space values: 0; empty/unknown-like values: 0; spelling/case collisions: 0

| class | count |
| --- | --- |
| fresh | 8774 |
| rotten | 8124 |
| rottenapples | 2943 |
| rottenbanana | 2754 |
| freshapples | 2088 |
| rottenoranges | 1998 |
| Donut | 1972 |
| Taco | 1971 |
| Pizza | 1964 |
| freshbanana | 1962 |
| Sandwich | 1955 |
| Hot Dog | 1952 |
| Burger | 1938 |
| Crispy Chicken | 1929 |
| Taquito | 1893 |
| freshoranges | 1854 |
| Baked Potato | 1834 |
| Fries | 1772 |

**condition** - 3 distinct values; leading/trailing-space values: 0; empty/unknown-like values: 32779; spelling/case collisions: 0

**source_dataset** - 3 distinct values; leading/trailing-space values: 0; empty/unknown-like values: 0; spelling/case collisions: 0

| source_dataset | count |
| --- | --- |
| FastFood | 19180 |
| FruitVegetable | 16898 |
| FruitQuality1 | 13599 |

**split** - 3 distinct values; leading/trailing-space values: 0; empty/unknown-like values: 0; spelling/case collisions: 0

| split | count |
| --- | --- |
| Train | 34789 |
| Validation | 7461 |
| Test | 7427 |


### 2.3 Food class mapping

| class_id | food | n_images | train | val | test | sources | fdc_ids | n_fdc_ids | flags |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Apple | 6158 | 4311 | 923 | 924 | FruitQuality1, FruitVegetable | 171688 | 1 | OK |
| 1 | Baked Potato | 1834 | 1284 | 276 | 274 | FastFood | 170093 | 1 | OK |
| 2 | Banana | 6235 | 4365 | 936 | 934 | FruitQuality1, FruitVegetable | 173944 | 1 | OK |
| 3 | Bell Pepper | 1147 | 803 | 173 | 171 | FruitVegetable | 170427 | 1 | OK |
| 4 | Burger | 1938 | 1357 | 291 | 290 | FastFood | 170693 | 1 | OK |
| 5 | Carrot | 1116 | 782 | 168 | 166 | FruitVegetable | 170393 | 1 | OK |
| 6 | Crispy Chicken | 1929 | 1353 | 289 | 287 | FastFood | 170343 | 1 | OK |
| 7 | Cucumber | 1167 | 817 | 176 | 174 | FruitVegetable | 168409 | 1 | OK |
| 8 | Donut | 1972 | 1381 | 296 | 295 | FastFood | 174990 | 1 | OK |
| 9 | Fries | 1772 | 1241 | 267 | 264 | FastFood | 169836 | 1 | OK |
| 10 | Grape | 400 | 280 | 60 | 60 | FruitVegetable | 174683 | 1 | LOW_DATA(<500) |
| 11 | Guava | 400 | 280 | 60 | 60 | FruitVegetable | 173044 | 1 | LOW_DATA(<500) |
| 12 | Hot Dog | 1952 | 1368 | 293 | 291 | FastFood | 171633 | 1 | OK |
| 13 | Jujube | 400 | 280 | 60 | 60 | FruitVegetable | 168151 | 1 | LOW_DATA(<500) |
| 14 | Mango | 3193 | 2236 | 479 | 478 | FruitVegetable | 169910 | 1 | OK |
| 15 | Orange | 4950 | 3468 | 743 | 739 | FruitQuality1, FruitVegetable | 169097 | 1 | OK |
| 16 | Pizza | 1964 | 1375 | 295 | 294 | FastFood | 170317 | 1 | OK |
| 17 | Pomegranate | 400 | 280 | 60 | 60 | FruitVegetable | 169134 | 1 | LOW_DATA(<500) |
| 18 | Potato | 1174 | 822 | 177 | 175 | FruitVegetable | 170026 | 1 | OK |
| 19 | Sandwich | 1955 | 1369 | 294 | 292 | FastFood | 170309 | 1 | OK |
| 20 | Strawberry | 2581 | 1807 | 388 | 386 | FruitVegetable | 167762 | 1 | OK |
| 21 | Taco | 1971 | 1380 | 296 | 295 | FastFood | 170689 | 1 | OK |
| 22 | Taquito | 1893 | 1326 | 284 | 283 | FastFood | 169771 | 1 | OK |
| 23 | Tomato | 1176 | 824 | 177 | 175 | FruitVegetable | 170457 | 1 | OK |

Class imbalance: largest class 6,235 images, smallest 400 (ratio 15.6x). Classes flagged LOW_DATA: 4.

Number of distinct foods contributed by each image source:

| source_dataset | foods |
| --- | --- |
| FastFood | 10 |
| FruitQuality1 | 3 |
| FruitVegetable | 14 |

Largest class-share deviation from overall: train 0.01 pp, val 0.03 pp, test 0.05 pp (small = splits are stratified).

Split sizes: train=34,789, val=7,461, test=7,427


### 2.4 Condition (freshness) labels

Rows whose `condition` is empty/Unknown: **32,779**. Of these, **13,599** have a class name that states fresh/rotten (heuristic: class contains 'fresh' or 'rotten'), so the label could be recovered. Rows where `condition` contradicts the class name: **0**.

Condition counts per food after recovery (Unknown = no usable freshness label):

| food | Fresh | Rotten | Unknown |
| --- | --- | --- | --- |
| Apple | 2802 | 3356 | 0 |
| Baked Potato | 0 | 0 | 1834 |
| Banana | 2944 | 3291 | 0 |
| Bell Pepper | 600 | 547 | 0 |
| Burger | 0 | 0 | 1938 |
| Carrot | 610 | 506 | 0 |
| Crispy Chicken | 0 | 0 | 1929 |
| Cucumber | 591 | 576 | 0 |
| Donut | 0 | 0 | 1972 |
| Fries | 0 | 0 | 1772 |
| Grape | 200 | 200 | 0 |
| Guava | 200 | 200 | 0 |
| Hot Dog | 0 | 0 | 1952 |
| Jujube | 200 | 200 | 0 |
| Mango | 1429 | 1764 | 0 |
| Orange | 2419 | 2531 | 0 |
| Pizza | 0 | 0 | 1964 |
| Pomegranate | 200 | 200 | 0 |
| Potato | 610 | 564 | 0 |
| Sandwich | 0 | 0 | 1955 |
| Strawberry | 1271 | 1310 | 0 |
| Taco | 0 | 0 | 1971 |
| Taquito | 0 | 0 | 1893 |
| Tomato | 602 | 574 | 0 |

Foods that have BOTH Fresh and Rotten examples (candidates for a freshness model): **14** - Apple, Banana, Bell Pepper, Carrot, Cucumber, Grape, Guava, Jujube, Mango, Orange, Pomegranate, Potato, Strawberry, Tomato

| food | fresh | rotten | train_fresh | train_rotten | val_fresh | val_rotten | test_fresh | test_rotten |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Apple | 2802 | 3356 | 1934 | 2377 | 435 | 488 | 433 | 491 |
| Banana | 2944 | 3291 | 2046 | 2319 | 463 | 473 | 435 | 499 |
| Bell Pepper | 600 | 547 | 423 | 380 | 90 | 83 | 87 | 84 |
| Carrot | 610 | 506 | 430 | 352 | 92 | 76 | 88 | 78 |
| Cucumber | 591 | 576 | 422 | 395 | 90 | 86 | 79 | 95 |
| Grape | 200 | 200 | 135 | 145 | 29 | 31 | 36 | 24 |
| Guava | 200 | 200 | 136 | 144 | 31 | 29 | 33 | 27 |
| Jujube | 200 | 200 | 147 | 133 | 28 | 32 | 25 | 35 |
| Mango | 1429 | 1764 | 983 | 1253 | 227 | 252 | 219 | 259 |
| Orange | 2419 | 2531 | 1693 | 1775 | 365 | 378 | 361 | 378 |
| Pomegranate | 200 | 200 | 142 | 138 | 35 | 25 | 23 | 37 |
| Potato | 610 | 564 | 423 | 399 | 96 | 81 | 91 | 84 |
| Strawberry | 1271 | 1310 | 885 | 922 | 198 | 190 | 188 | 198 |
| Tomato | 602 | 574 | 433 | 391 | 84 | 93 | 85 | 90 |

Foods with NO usable Fresh/Rotten pair (a freshness model cannot be trained or evaluated for them): Baked Potato, Burger, Crispy Chicken, Donut, Fries, Hot Dog, Pizza, Sandwich, Taco, Taquito


### 2.5 Nutrient columns

| nutrient | missing_rows | missing_% | foods_with_missing | negative_values |
| --- | --- | --- | --- | --- |
| fiber_g | 400 | 0.81 | Jujube | 0 |
| sugars_g | 400 | 0.81 | Jujube | 0 |
| selenium_ug | 400 | 0.81 | Jujube | 0 |
| vitamin_c_mg | 1929 | 3.88 | Crispy Chicken | 0 |
| vitamin_e_mg | 2329 | 4.69 | Crispy Chicken, Jujube | 0 |
| vitamin_k_ug | 2329 | 4.69 | Crispy Chicken, Jujube | 0 |
| folate_dfe_ug | 4101 | 8.26 | Crispy Chicken, Fries, Jujube | 0 |
| vitamin_b12_ug | 1772 | 3.57 | Fries | 0 |
| vitamin_d_ug | 4101 | 8.26 | Crispy Chicken, Fries, Jujube | 0 |

Missing nutrients above must stay 'not available' in the app (never 0).

Nutrient values that differ between rows of the same food: **0** (0 means each food has one reference record).

Energy vs Atwater estimate (4P+4C+9F): foods differing by more than 20%: none.

Nutrient basis is NOT stored in the CSV. The values must be documented as per 100 g (USDA reference) in the API.


### 2.6 Identifiers, paths and filenames

Duplicate image_id values: **0**.

Duplicate image_path values: **0**.

Where the CSV expects the images to be (first path components):

| path_prefix | rows |
| --- | --- |
| D:/Food_Composition_Project/images | 49677 |

File extensions: .jpeg=19,036, .jpg=15,522, .png=15,105, .webp=14

Rows sharing an image_name with another row: 4,000 (informational: same filename in different folders is not a duplicate image; never use the filename alone as an identifier).


### 2.7 Pre-augmented copies and split leakage (filename-based)

Filenames starting with an augmentation prefix (^(?:rotated_by_\d+|translation|flipped|flip|zoom|shear)_): **9,066**.

| prefix | rows |
| --- | --- |
| rotated_by_15_ | 1511 |
| rotated_by_30_ | 1511 |
| rotated_by_45_ | 1511 |
| rotated_by_60_ | 1511 |
| rotated_by_75_ | 1511 |
| translation_ | 1511 |

Families (original + its augmented copies) with more than one file: **1,511**. Families whose files sit in DIFFERENT splits: **1,381** (9,667 images).

Test images that have a train/validation 'twin' from the same family: **1,582** (21.3% of the test set).


### 2.8 Image files: existence, decoding, exact and near duplicates

Scanned **49,677** images: found **49,677**, missing **0**, exist but cannot be decoded **0**, valid **49,677**.

Image size/format statistics (valid images):

| stat | value |
| --- | --- |
| width min / median / max | 80 / 275 / 7599 |
| height min / median / max | 88 / 225 / 6000 |
| file KB min / median / max | 1 / 12 / 14832 |
| images smaller than 64px (either side) | 0 |

Formats: JPEG=34,477, PNG=15,182, WEBP=17, MPO=1 | Modes: RGB=48,027, RGBA=1,622, P=27, CMYK=1


#### Exact duplicates (identical file bytes)

| groups | images_in_groups | groups_cross_split | images_in_cross_split_groups | groups_cross_label | test_images_with_train_or_val_twin |
| --- | --- | --- | --- | --- | --- |
| 0 | 0 | 0 | 0 | 0 | 0 |


#### Near duplicates (perceptual hash distance <= 2 of 64 bits)

| groups | images_in_groups | groups_cross_split | images_in_cross_split_groups | groups_cross_label | test_images_with_train_or_val_twin |
| --- | --- | --- | --- | --- | --- |
| 3064 | 6981 | 1172 | 3088 | 25 | 752 |

Perceptual hashing catches resized / re-compressed / lightly edited copies. It does NOT catch strongly rotated or shifted copies (see section 2.7 for those) and may flag genuinely similar photos; treat these as candidates to review, not proof.


## 3. Packaged food nutrition table (packaged_foods_india_clean.csv)

Rows: **852**, columns: **26**.

| column | dtype | non_null | missing | missing_% | unique |
| --- | --- | --- | --- | --- | --- |
| product_id | int64 | 852 | 0 | 0.0 | 852 |
| S.No | int64 | 852 | 0 | 0.0 | 852 |
| Item name | str | 852 | 0 | 0.0 | 843 |
| Brand_Name | str | 852 | 0 | 0.0 | 262 |
| Category | str | 852 | 0 | 0.0 | 13 |
| Sub_Category | str | 852 | 0 | 0.0 | 197 |
| Ingredients | str | 852 | 0 | 0.0 | 848 |
| Serving_Size_g | float64 | 852 | 0 | 0.0 | 34 |
| Calories_kcal | float64 | 851 | 1 | 0.12 | 541 |
| Carbohydrates_g | float64 | 851 | 1 | 0.12 | 519 |
| Proteins_g | float64 | 848 | 4 | 0.47 | 253 |
| Total_Fat_g | float64 | 845 | 7 | 0.82 | 374 |
| Saturated_Fat_g | float64 | 842 | 10 | 1.17 | 277 |
| Trans_Fat_g | float64 | 832 | 20 | 2.35 | 39 |
| Sugar_g | float64 | 844 | 8 | 0.94 | 421 |
| Sodium_mg | float64 | 845 | 7 | 0.82 | 535 |
| Dietary_Fiber_g | float64 | 842 | 10 | 1.17 | 120 |
| Cholesterol_mg | float64 | 827 | 25 | 2.93 | 151 |
| Calcium_mg | float64 | 846 | 6 | 0.7 | 79 |
| Vitamin | str | 847 | 5 | 0.59 | 75 |
| Iron_mg | float64 | 845 | 7 | 0.82 | 44 |
| Price_INR | float64 | 845 | 7 | 0.82 | 132 |
| Source_of_Data | str | 2 | 850 | 99.77 | 2 |
| Collection_Date | str | 3 | 849 | 99.65 | 3 |
| Collected_By | float64 | 0 | 852 | 100.0 | 0 |
| Remarks | float64 | 0 | 852 | 100.0 | 0 |

Duplicate product_id: **0**.


### 3.1 Zero values that may really be 'not listed'

| column | rows_equal_0_% | missing_% |
| --- | --- | --- |
| Serving_Size_g | 0.0 | 0.0 |
| Carbohydrates_g | 0.8 | 0.1 |
| Proteins_g | 12.7 | 0.5 |
| Total_Fat_g | 16.4 | 0.8 |
| Saturated_Fat_g | 23.9 | 1.2 |
| Trans_Fat_g | 68.4 | 2.3 |
| Sugar_g | 7.9 | 0.9 |
| Sodium_mg | 15.6 | 0.8 |
| Dietary_Fiber_g | 70.4 | 1.2 |
| Cholesterol_mg | 68.4 | 2.9 |
| Calcium_mg | 87.3 | 0.7 |
| Iron_mg | 92.4 | 0.8 |

Rows where calcium AND iron are both exactly 0: **85.3%**. Real foods rarely have both at exactly zero, so these zeros most likely mean 'not on the label'. They must be treated as missing, not zero.

`Vitamin` is free text; value '0' appears in 768 rows (again, '0' means 'not listed').


### 3.2 Serving basis

Serving_Size_g equals 100 in **780** rows and differs in **72** rows. There is NO column that says whether nutrient values are per 100 g or per serving, so the basis of those rows is ambiguous.


### 3.3 Impossible or suspicious values

| reason | rows |
| --- | --- |
| energy differs >35% from 4P+4C+9F estimate (verify) | 28 |
| sugar greater than total carbohydrate | 12 |
| carbs+protein+fat exceed the food's weight | 11 |
| fiber greater than total carbohydrate | 5 |
| saturated fat greater than total fat | 4 |
| 0 kcal listed (check: water-like drink or missing?) | 3 |
| carbohydrates exceeds carbohydrates possible in its g (impossible) | 2 |
| fiber exceeds fiber possible in its g (impossible) | 2 |
| energy above 9.5 kcal per gram (impossible) | 1 |

52 distinct rows flagged (full list: reports/packaged_food_flags.csv).


### 3.4 Duplicates and provenance

Rows sharing the same name+brand with another row: **18**; exact full-row duplicates (ignoring ids): **1**.

Provenance fields filled in (of 852 rows): {'source': 2, 'date': 3, 'by': 0}

This table has no product images or barcodes, so it cannot be used to train or test OCR.


## 4. Additive occurrences (packaged_food_additives.csv)

Rows: **1,268**, columns: **7**.

| column | dtype | non_null | missing | missing_% | unique |
| --- | --- | --- | --- | --- | --- |
| product_id | int64 | 1268 | 0 | 0.0 | 309 |
| item_name | str | 1268 | 0 | 0.0 | 306 |
| brand | str | 1268 | 0 | 0.0 | 124 |
| category | str | 1268 | 0 | 0.0 | 13 |
| ingredient_text | str | 1268 | 0 | 0.0 | 309 |
| ins_code_exact | str | 1268 | 0 | 0.0 | 127 |
| ins_code_base | str | 1268 | 0 | 0.0 | 126 |

Distinct products: **309**, distinct base INS codes: **126**, distinct exact codes: **127**. Duplicate (product, exact code) rows: **0**.

This file lists WHICH additives each product contains. It has no function/regulatory columns; explanations come from the reference table (section 5).


### 4.1 Code format screen (not a verification against Codex)

| code | issue | rows |
| --- | --- | --- |
| INS 1500 | 4-digit code outside the common INS blocks - verify manually | 3 |
| INS 2021 | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) | 1 |
| INS 2620 | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) | 1 |
| INS 3076 | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) | 1 |
| INS 3310 | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) | 1 |
| INS 4221 | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) | 1 |
| INS 4500 | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) | 1 |
| INS 5330 | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) | 1 |


### 4.2 Consistency with the packaged-food table

Additive rows whose product_id is not in the packaged table: **0**; ingredient text differs from the packaged table: **0**.


### 4.3 Additives written in the ingredient text but missing from this table

Products with an `INS ###` / `E###` code in the text that is NOT in the additive table: **105**. Products with extra codes written like 'EMULSIFIER [472e]': **187**. (Regex screen; review before trusting.)

Most common missed codes: 150 x28, 322 x20, 330 x20, 500 x17, 407 x9, 503 x8, 102 x8, 160 x8, 472 x7, 476 x7, 471 x7, 412 x7

| product_id | missing_INS_or_E_codes | missing_keyword_codes |
| --- | --- | --- |
| 1 |  | 500, 503 |
| 2 |  | 223, 322, 471, 500, 503 |
| 3 | 150 |  |
| 4 | 150 |  |
| 6 |  | 322, 503 |
| 8 |  | 322, 471 |
| 13 | 3221, 3411, 407, 410, 415, 440, 500, 503 |  |
| 14 |  | 223, 322, 450, 471, 500, 503 |
| 16 |  | 322, 450, 471, 500, 503 |
| 20 |  | 322, 500, 503 |

Products with at least one extracted additive: 309 of 852 (36%).


## 5. Additive reference table (additive_reference_populated.csv)

Rows: **126**, columns: **7**.

| column | dtype | non_null | missing | missing_% | unique |
| --- | --- | --- | --- | --- | --- |
| ins_code | str | 126 | 0 | 0.0 | 126 |
| additive_name | str | 126 | 0 | 0.0 | 124 |
| functional_class | str | 126 | 0 | 0.0 | 63 |
| jecfa_status | str | 126 | 0 | 0.0 | 29 |
| codex_status | str | 126 | 0 | 0.0 | 22 |
| safety_note | str | 126 | 0 | 0.0 | 122 |
| source | str | 126 | 0 | 0.0 | 3 |

Duplicate ins_code values: **0**.


### 5.1 Format screen of reference codes

| ins_code | name | issue |
| --- | --- | --- |
| INS 1500 | Sodium Lactate | 4-digit code outside the common INS blocks - verify manually |
| INS 2021 | Potassium Sorbate Solution | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) |
| INS 2620 | Sodium Acetate Anhydrous | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) |
| INS 3076 | Alpha-Tocopherol Synthetic | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) |
| INS 3310 | Trisodium Citrate Anhydrous | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) |
| INS 4221 | Glycerol Monostearate Pure | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) |
| INS 4500 | Disodium Diphosphate | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) |
| INS 5330 | Magnesium Silicate Anti-caking | 4-digit code not starting with 1 (no such INS block - likely a sub-variant glued onto a 3-digit code) |


### 5.2 How informative are the regulatory fields?

`jecfa_status` entries without any ADI figure or explicit 'ADI not specified/no ADI': **13** (values: Acceptable, Evaluated, Under Review).

`safety_note` distinct values: **122** of 126; most repeated: {'Modified food starch': 4, 'Buffering agent': 2, 'Synthetic azo dye; monitor in sensitive individuals': 1}.

`source` values naming a specific document/URL: **0** of 126 (values seen: {'Codex Alimentarius / FSSAI': 99, 'JECFA / FSSAI': 26, 'FSSAI': 1}).


### 5.3 Coverage

Codes used by products but missing from the reference: **0**. Reference codes never used by any product: **0**.

This script can only screen format and consistency. It cannot verify the regulatory content itself.


## 6. OCR dataset inventory (--ocr-dir)

Total files: **21,847**, image files: **21,840**.

| extension | files |
| --- | --- |
| .jpg | 21840 |
| .txt | 7 |

| top-level folder | files |
| --- | --- |
| det | 10923 |
| rec | 10923 |
| (root) | 1 |

Label/annotation file candidates (first lines shown so we learn the real format before building anything):

`README.txt`:
```
Food Packaging OCR Dataset

Food Packaging OCR Dataset/
```

`det\test\labels.txt`:
```
0001.jpg	[{"transcription": "UDDER", "points": [[152, 127], [212, 127], [212, 181], [152, 181]]}, {"transcription": "CHOCOLUSH", "points": [[117, 235], [189, 23
0002.jpg	[{"transcription": "CHEESE", "points": [[111, 157], [239, 157], [239, 185], [111, 185]]}, {"transcription": "1.5", "points": [[105, 200], [122, 200], [
0003.jpg	[{"transcription": "CHOCOLATE", "points": [[48, 374], [102, 374], [102, 381], [48, 381]]}, {"transcription": "g", "points": [[130, 383], [136, 383], [1
```

`det\train\labels.txt`:
```
0001.jpg	[{"transcription": "kazidomi", "points": [[113, 107], [247, 110], [247, 131], [113, 128]]}, {"transcription": "My", "points": [[101, 138], [139, 139], 
0002.jpg	[{"transcription": "ABTEY", "points": [[126, 306], [228, 310], [227, 337], [125, 333]]}, {"transcription": "CHOCOLATIER", "points": [[132, 340], [182, 
0003.jpg	[{"transcription": "VAN", "points": [[0, 104], [82, 91], [91, 150], [8, 163]]}, {"transcription": "HOUTEN", "points": [[84, 89], [299, 54], [299, 115],
```

`det\valid\labels.txt`:
```
0001.jpg	[{"transcription": "NO", "points": [[63, 24], [78, 24], [78, 33], [63, 33]]}, {"transcription": "PLASTIC", "points": [[82, 23], [121, 24], [121, 34], [
0002.jpg	[{"transcription": "simple", "points": [[134, 65], [167, 64], [167, 73], [134, 74]]}, {"transcription": "truth", "points": [[169, 64], [196, 63], [196,
0003.jpg	[{"transcription": "PRIVATE", "points": [[179, 37], [226, 37], [226, 44], [179, 44]]}, {"transcription": "SELECTION", "points": [[177, 46], [228, 46], 
```

`rec\test\labels.txt`:
```
﻿0001.jpg	for
0002.jpg	crispy
0003.jpg	texture
```

`rec\train\labels.txt`:
```
﻿0001.jpg	kazidomi
0002.jpg	My
0003.jpg	VAN
```

