# SmartPlateAI - Phase 4 Training Report

Run: `food_head_full_01` | stage: head | generated 2026-10-11 16:24:23

## Configuration

```json
{
  "stage": "head",
  "image_size": 224,
  "batch_size": 32,
  "epochs_requested": 8,
  "epochs_run": 8,
  "learning_rate": 0.001,
  "seed": 42,
  "subset_caps": {
    "train": 0,
    "val": 0
  },
  "class_weight_source": "reports/phase3/class_weights.json",
  "train_images": 34745,
  "val_images": 7456,
  "train_seconds": 5305.4,
  "train_images_per_second": 52.39,
  "finetune": null
}
```

## Class imbalance (training images used) and weights

| food | train_images_used | class_weight |
| --- | --- | --- |
| Apple | 4309 | 0.3361 |
| Baked Potato | 1284 | 1.1279 |
| Banana | 4363 | 0.3319 |
| Bell Pepper | 803 | 1.8034 |
| Burger | 1356 | 1.068 |
| Carrot | 780 | 1.8566 |
| Crispy Chicken | 1349 | 1.0735 |
| Cucumber | 815 | 1.7769 |
| Donut | 1380 | 1.0494 |
| Fries | 1240 | 1.1679 |
| Grape | 280 | 5.172 |
| Guava | 280 | 5.172 |
| Hot Dog | 1366 | 1.0602 |
| Jujube | 280 | 5.172 |
| Mango | 2233 | 0.6485 |
| Orange | 3464 | 0.4181 |
| Pizza | 1374 | 1.054 |
| Pomegranate | 280 | 5.172 |
| Potato | 820 | 1.7661 |
| Sandwich | 1368 | 1.0586 |
| Strawberry | 1805 | 0.8023 |
| Taco | 1379 | 1.0502 |
| Taquito | 1325 | 1.093 |
| Tomato | 823 | 1.7596 |

## Validation results (best checkpoint; validation data guided checkpoint selection)

### Subset: all (n=7,456)

accuracy 0.9072 | macro precision 0.8816 | macro recall 0.9008 | macro F1 0.8896 | weighted F1 0.9074 | top-3 0.9751 | log loss 0.3096

Weakest 8 classes by F1:

| class_id | food | support | precision | recall | f1 |
| --- | --- | --- | --- | --- | --- |
| 21 | Taco | 296 | 0.6809 | 0.6993 | 0.69 |
| 22 | Taquito | 284 | 0.7727 | 0.7183 | 0.7445 |
| 19 | Sandwich | 294 | 0.8284 | 0.7551 | 0.79 |
| 4 | Burger | 291 | 0.8006 | 0.8694 | 0.8336 |
| 1 | Baked Potato | 275 | 0.8027 | 0.8727 | 0.8362 |
| 12 | Hot Dog | 293 | 0.8935 | 0.802 | 0.8453 |
| 11 | Guava | 60 | 0.7662 | 0.9833 | 0.8613 |
| 8 | Donut | 296 | 0.8138 | 0.9155 | 0.8617 |

Most frequent confusions:

| true | predicted_as | images |
| --- | --- | --- |
| Taquito | Taco | 32 |
| Taco | Taquito | 19 |
| Sandwich | Burger | 19 |
| Taco | Baked Potato | 15 |
| Hot Dog | Taquito | 14 |
| Apple | Guava | 14 |
| Pizza | Taco | 13 |
| Sandwich | Taco | 13 |
| Taco | Sandwich | 13 |
| Orange | Mango | 12 |


### Subset: original_only (n=6,082)

accuracy 0.8893 | macro precision 0.8823 | macro recall 0.8971 | macro F1 0.8881 | weighted F1 0.8894 | top-3 0.9696 | log loss 0.3701

Weakest 8 classes by F1:

| class_id | food | support | precision | recall | f1 |
| --- | --- | --- | --- | --- | --- |
| 21 | Taco | 296 | 0.6809 | 0.6993 | 0.69 |
| 22 | Taquito | 284 | 0.7727 | 0.7183 | 0.7445 |
| 19 | Sandwich | 294 | 0.8284 | 0.7551 | 0.79 |
| 4 | Burger | 291 | 0.8006 | 0.8694 | 0.8336 |
| 1 | Baked Potato | 275 | 0.8027 | 0.8727 | 0.8362 |
| 12 | Hot Dog | 293 | 0.8935 | 0.802 | 0.8453 |
| 6 | Crispy Chicken | 290 | 0.8328 | 0.8931 | 0.8619 |
| 8 | Donut | 296 | 0.8163 | 0.9155 | 0.8631 |

Most frequent confusions:

| true | predicted_as | images |
| --- | --- | --- |
| Taquito | Taco | 32 |
| Taco | Taquito | 19 |
| Sandwich | Burger | 19 |
| Taco | Baked Potato | 15 |
| Hot Dog | Taquito | 14 |
| Sandwich | Taco | 13 |
| Pizza | Taco | 13 |
| Taco | Sandwich | 13 |
| Apple | Guava | 13 |
| Orange | Mango | 12 |


## Test set

Not evaluated in this run (by design).

## Limitations

- The model only knows the 24 foods in the dataset. Any other food, a drink, an empty plate or a non-food photo is still forced into one of
  the 24 classes: it has no "other / not food" class. A softmax score is not a probability that the answer is correct.
- Images come from three public image sources. Fast-food classes come from one source and most fruit/vegetable classes from one
  source each, so the model can partly learn each source's photo style. Expect lower accuracy on your own phone photos.
- Apple, banana and orange include pre-augmented copies (rotated/shifted). Headline metrics should use the `original_only` subset.
- Near-duplicate detection in Phase 3 cannot catch rotated or cropped copies of the same photo, so small residual leakage is possible.
- Class imbalance is handled with class weights only; per-class recall matters more than overall accuracy.
- Freshness is not predicted by this model.
