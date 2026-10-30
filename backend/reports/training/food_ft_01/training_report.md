# SmartPlateAI - Phase 4 Training Report

Run: `food_ft_01` | stage: finetune | generated 2026-10-11 17:12:26

## Configuration

```json
{
  "stage": "finetune",
  "image_size": 224,
  "batch_size": 32,
  "epochs_requested": 3,
  "epochs_run": 3,
  "learning_rate": 1e-05,
  "seed": 42,
  "subset_caps": {
    "train": 0,
    "val": 0
  },
  "class_weight_source": "reports/phase3/class_weights.json",
  "train_images": 34745,
  "val_images": 7456,
  "train_seconds": 2392.6,
  "train_images_per_second": 43.57,
  "finetune": {
    "backbone_layers": 154,
    "unfrozen_last_n": 30,
    "trainable_parameters": 1541464
  }
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

accuracy 0.9194 | macro precision 0.9041 | macro recall 0.9074 | macro F1 0.9048 | weighted F1 0.9194 | top-3 0.9792 | log loss 0.2676

Weakest 8 classes by F1:

| class_id | food | support | precision | recall | f1 |
| --- | --- | --- | --- | --- | --- |
| 21 | Taco | 296 | 0.6852 | 0.75 | 0.7161 |
| 22 | Taquito | 284 | 0.7931 | 0.7289 | 0.7596 |
| 19 | Sandwich | 294 | 0.8496 | 0.7687 | 0.8071 |
| 4 | Burger | 291 | 0.8006 | 0.8832 | 0.8399 |
| 12 | Hot Dog | 293 | 0.8828 | 0.8225 | 0.8516 |
| 1 | Baked Potato | 275 | 0.8328 | 0.8873 | 0.8592 |
| 8 | Donut | 296 | 0.8553 | 0.9189 | 0.886 |
| 6 | Crispy Chicken | 290 | 0.9011 | 0.8793 | 0.8901 |

Most frequent confusions:

| true | predicted_as | images |
| --- | --- | --- |
| Taquito | Taco | 36 |
| Sandwich | Burger | 20 |
| Taco | Taquito | 18 |
| Sandwich | Taco | 17 |
| Pizza | Taco | 13 |
| Hot Dog | Taquito | 13 |
| Taco | Hot Dog | 12 |
| Bell Pepper | Tomato | 11 |
| Apple | Orange | 11 |
| Fries | Burger | 11 |


### Subset: original_only (n=6,082)

accuracy 0.9027 | macro precision 0.9029 | macro recall 0.9050 | macro F1 0.9030 | weighted F1 0.9027 | top-3 0.9747 | log loss 0.3229

Weakest 8 classes by F1:

| class_id | food | support | precision | recall | f1 |
| --- | --- | --- | --- | --- | --- |
| 21 | Taco | 296 | 0.6852 | 0.75 | 0.7161 |
| 22 | Taquito | 284 | 0.7931 | 0.7289 | 0.7596 |
| 19 | Sandwich | 294 | 0.8496 | 0.7687 | 0.8071 |
| 4 | Burger | 291 | 0.8031 | 0.8832 | 0.8412 |
| 12 | Hot Dog | 293 | 0.8828 | 0.8225 | 0.8516 |
| 1 | Baked Potato | 275 | 0.8328 | 0.8873 | 0.8592 |
| 8 | Donut | 296 | 0.8553 | 0.9189 | 0.886 |
| 6 | Crispy Chicken | 290 | 0.9011 | 0.8793 | 0.8901 |

Most frequent confusions:

| true | predicted_as | images |
| --- | --- | --- |
| Taquito | Taco | 36 |
| Sandwich | Burger | 20 |
| Taco | Taquito | 18 |
| Sandwich | Taco | 17 |
| Pizza | Taco | 13 |
| Hot Dog | Taquito | 13 |
| Taco | Hot Dog | 12 |
| Bell Pepper | Tomato | 11 |
| Fries | Burger | 11 |
| Hot Dog | Taco | 10 |


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
