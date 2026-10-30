# SmartPlateAI - Phase 3 Split Report
Generated 2026-10-10 23:47:05 | script v3.0 | seed 42 | ratios (0.7, 0.15, 0.15) | near-duplicate distance <= 2 | max near-merge group size 2000


## 1. Leakage validation

| check | result | detail | type |
| --- | --- | --- | --- |
| image_id unique | PASS | 0 duplicates | hard |
| every image has a split in {train,val,test} | PASS | 0 invalid | hard |
| no group_id crosses splits | PASS | 0 groups cross splits of 36,777 | hard |
| no byte-identical image (SHA-256) crosses splits | PASS | 0 hashes cross splits | hard |
| no augmentation family (recomputed from filenames) crosses splits | PASS | 0 families cross splits of 40,611 | hard |
| near-duplicate pairs (dHash distance <= 2) crossing splits | PASS | 0 of 18,562 near-duplicate pairs cross splits | soft |

`FAIL` on a hard check means the split is invalid. `REVIEW` means near-duplicate pairs remain across splits (see section 6 and near_duplicate_conflicts.csv).


## 2. Exclusions

Source rows: 49,677. Included: 49,677. Excluded: 0 (list: data_prep\excluded_samples.csv).

_(none)_


## 3. Group construction

Groups: 36,777 for 49,677 images. Multi-image groups: 3,066 (largest 302 images). Merges: family 9,066, exact-duplicate 0, near-duplicate 3,834; near-duplicate merges refused by the size cap: 0.

| group_size | groups |
| --- | --- |
| 1 | 33711 |
| 2 | 1476 |
| 3 | 123 |
| 4 | 32 |
| 5 | 6 |
| 6 | 9 |
| 7 | 226 |
| 8 | 1038 |
| 9 | 61 |
| 10 | 10 |
| 11 | 1 |
| 12 | 2 |
| 13 | 1 |
| 14 | 3 |
| 15 | 13 |

_... 19 more rows not shown._

Groups whose images carry more than one food label: 25 (kept together in one split; listed in label_conflict_groups.csv for manual review). Byte-identical images with conflicting labels were excluded (section 2).


## 4. Split result

Image counts: train=34,756 (70.0%), val=7,461 (15.0%), test=7,460 (15.0%)

| food | class_id | train | val | test | total | train_% | val_% | test_% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Apple | 0 | 4309 | 925 | 924 | 6158 | 70.0 | 15.0 | 15.0 |
| Baked Potato | 1 | 1284 | 275 | 275 | 1834 | 70.0 | 15.0 | 15.0 |
| Banana | 2 | 4363 | 936 | 936 | 6235 | 70.0 | 15.0 | 15.0 |
| Bell Pepper | 3 | 803 | 172 | 172 | 1147 | 70.0 | 15.0 | 15.0 |
| Burger | 4 | 1356 | 291 | 291 | 1938 | 70.0 | 15.0 | 15.0 |
| Carrot | 5 | 780 | 168 | 168 | 1116 | 69.9 | 15.1 | 15.1 |
| Crispy Chicken | 6 | 1349 | 290 | 290 | 1929 | 69.9 | 15.0 | 15.0 |
| Cucumber | 7 | 815 | 176 | 176 | 1167 | 69.8 | 15.1 | 15.1 |
| Donut | 8 | 1380 | 296 | 296 | 1972 | 70.0 | 15.0 | 15.0 |
| Fries | 9 | 1240 | 266 | 266 | 1772 | 70.0 | 15.0 | 15.0 |
| Grape | 10 | 280 | 60 | 60 | 400 | 70.0 | 15.0 | 15.0 |
| Guava | 11 | 280 | 60 | 60 | 400 | 70.0 | 15.0 | 15.0 |
| Hot Dog | 12 | 1366 | 293 | 293 | 1952 | 70.0 | 15.0 | 15.0 |
| Jujube | 13 | 280 | 60 | 60 | 400 | 70.0 | 15.0 | 15.0 |
| Mango | 14 | 2233 | 480 | 480 | 3193 | 69.9 | 15.0 | 15.0 |
| Orange | 15 | 3464 | 743 | 743 | 4950 | 70.0 | 15.0 | 15.0 |
| Pizza | 16 | 1374 | 295 | 295 | 1964 | 70.0 | 15.0 | 15.0 |
| Pomegranate | 17 | 280 | 60 | 60 | 400 | 70.0 | 15.0 | 15.0 |
| Potato | 18 | 820 | 177 | 177 | 1174 | 69.8 | 15.1 | 15.1 |
| Sandwich | 19 | 1368 | 294 | 293 | 1955 | 70.0 | 15.0 | 15.0 |
| Strawberry | 20 | 1805 | 388 | 388 | 2581 | 69.9 | 15.0 | 15.0 |
| Taco | 21 | 1379 | 296 | 296 | 1971 | 70.0 | 15.0 | 15.0 |
| Taquito | 22 | 1325 | 284 | 284 | 1893 | 70.0 | 15.0 | 15.0 |
| Tomato | 23 | 823 | 176 | 177 | 1176 | 70.0 | 15.0 | 15.1 |

Original (non-augmented) images per split - use these for headline test metrics, because pre-augmented rotated/shifted copies do not resemble real user photos: train=28,438, val=6,087, test=6,086

| source_dataset | train | val | test |
| --- | --- | --- | --- |
| FastFood | 13421 | 2880 | 2879 |
| FruitQuality1 | 9455 | 2075 | 2069 |
| FruitVegetable | 11880 | 2506 | 2512 |


## 5. Class imbalance and class weights (computed on the train split only)

Train imbalance ratio 15.6x (largest 4,363, smallest 280). Remedy for training: the class weights in reports\phase3\class_weights.json plus macro-averaged metrics. No resampling or augmentation was applied in this phase.

| food | train_images | class_weight |
| --- | --- | --- |
| Apple | 4309 | 0.33608 |
| Baked Potato | 1284 | 1.127856 |
| Banana | 4363 | 0.33192 |
| Bell Pepper | 803 | 1.803445 |
| Burger | 1356 | 1.06797 |
| Carrot | 780 | 1.856624 |
| Crispy Chicken | 1349 | 1.073511 |
| Cucumber | 815 | 1.776892 |
| Donut | 1380 | 1.049396 |
| Fries | 1240 | 1.167876 |
| Grape | 280 | 5.172024 |
| Guava | 280 | 5.172024 |
| Hot Dog | 1366 | 1.060151 |
| Jujube | 280 | 5.172024 |
| Mango | 2233 | 0.64853 |
| Orange | 3464 | 0.418062 |
| Pizza | 1374 | 1.053979 |
| Pomegranate | 280 | 5.172024 |
| Potato | 820 | 1.766057 |
| Sandwich | 1368 | 1.058601 |
| Strawberry | 1805 | 0.802308 |
| Taco | 1379 | 1.050157 |
| Taquito | 1325 | 1.092956 |
| Tomato | 823 | 1.759619 |


## 6. Near-duplicate residuals

Near-duplicate pairs still crossing splits: 0. Non-zero only when the group-size cap refused a merge.


## 7. Freshness / condition labels

`condition` values are never inferred from food names. Rule R1 (documented): for source FruitQuality1 only, the source folder name (freshapples, rottenapples, freshbanana, ...) must equal the CSV `class` and map to the CSV `food`; then it is a *candidate* label. Candidates are used for stratification only. They become training labels only if you run with --accept-folder-rule (accepted this run: False). Original-label vs class contradictions set to Unknown: 0; candidate families with inconsistent labels dropped: 0.

| freshness_label_source | freshness_label | images |
| --- | --- | --- |
| none | Unknown | 32779 |
| original_label | Fresh | 8774 |
| original_label | Rotten | 8124 |

Images with a pending R1 candidate label: 13,599. Trainable freshness images now: 16,898. Everything else stays Unknown and is excluded from freshness training.

| food | freshness_label | train | val | test |
| --- | --- | --- | --- | --- |
| Apple | Fresh | 521 | 89 | 104 |
| Apple | Rotten | 288 | 70 | 55 |
| Banana | Fresh | 698 | 141 | 143 |
| Banana | Rotten | 391 | 70 | 76 |
| Bell Pepper | Fresh | 420 | 90 | 90 |
| Bell Pepper | Rotten | 383 | 82 | 82 |
| Carrot | Fresh | 426 | 92 | 92 |
| Carrot | Rotten | 354 | 76 | 76 |
| Cucumber | Fresh | 413 | 89 | 89 |
| Cucumber | Rotten | 402 | 87 | 87 |
| Grape | Fresh | 140 | 30 | 30 |
| Grape | Rotten | 140 | 30 | 30 |
| Guava | Fresh | 140 | 30 | 30 |
| Guava | Rotten | 140 | 30 | 30 |
| Jujube | Fresh | 140 | 30 | 30 |
| Jujube | Rotten | 140 | 30 | 30 |
| Mango | Fresh | 999 | 215 | 215 |
| Mango | Rotten | 1234 | 265 | 265 |
| Orange | Fresh | 396 | 84 | 85 |
| Orange | Rotten | 387 | 75 | 71 |
| Pomegranate | Fresh | 140 | 30 | 30 |
| Pomegranate | Rotten | 140 | 30 | 30 |
| Potato | Fresh | 426 | 92 | 92 |
| Potato | Rotten | 394 | 85 | 85 |
| Strawberry | Fresh | 889 | 191 | 191 |
| Strawberry | Rotten | 916 | 197 | 197 |
| Tomato | Fresh | 421 | 90 | 91 |
| Tomato | Rotten | 402 | 86 | 86 |


## 8. Packaged-food nutrition and additive data

Not part of the image split. Phase 1 data-quality flags are unchanged and nothing was repaired or imputed.

- `packaged_food_flags.csv`: 68 flagged rows

- `additive_extraction_gaps.csv`: 289 flagged rows


## 9. Assumptions and limitations

- Groups link images by filename family, identical bytes and 64-bit dHash distance <= 2. The dHash comparison is exhaustive (no bucket is skipped), but dHash only detects resized, re-compressed or lightly edited copies. Rotated, flipped, cropped or strongly recoloured copies of one photo, and different photos of the same object, are NOT detected unless their filename prefix is in the augmentation list.
- Residual leakage from undetected augmentations is therefore possible. Spot-check a few test images against train before trusting any test score.
- Near-duplicate merges are capped at 2000 images per group to stop chains of similar flat/white-background photos from forming giant groups; refused merges appear in section 6.
- Source confounding remains: fast-food classes come from one image source and most fruit/vegetable classes from one source each.
- Stratification is by food plus best-available condition (original label, else pending candidate, else Unknown).
- No model was trained and no accuracy is claimed.
