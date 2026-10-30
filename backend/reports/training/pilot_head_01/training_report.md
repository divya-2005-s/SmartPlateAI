# SmartPlateAI - Phase 4 Training Report

Run: `pilot_head_01` | stage: head | generated 2026-10-11 08:37:10

## Configuration

```json
{
  "stage": "head",
  "image_size": 224,
  "batch_size": 32,
  "epochs_requested": 3,
  "epochs_run": 3,
  "learning_rate": 0.001,
  "seed": 42,
  "subset_caps": {
    "train": 50,
    "val": 20
  },
  "class_weight_source": "recomputed from the capped pilot subset (same formula)",
  "train_images": 1200,
  "val_images": 480,
  "train_seconds": 86.6,
  "train_images_per_second": 41.58,
  "finetune": null
}
```

## Class imbalance (training images used) and weights

| food | train_images_used | class_weight |
| --- | --- | --- |
| Apple | 50 | 1.0 |
| Baked Potato | 50 | 1.0 |
| Banana | 50 | 1.0 |
| Bell Pepper | 50 | 1.0 |
| Burger | 50 | 1.0 |
| Carrot | 50 | 1.0 |
| Crispy Chicken | 50 | 1.0 |
| Cucumber | 50 | 1.0 |
| Donut | 50 | 1.0 |
| Fries | 50 | 1.0 |
| Grape | 50 | 1.0 |
| Guava | 50 | 1.0 |
| Hot Dog | 50 | 1.0 |
| Jujube | 50 | 1.0 |
| Mango | 50 | 1.0 |
| Orange | 50 | 1.0 |
| Pizza | 50 | 1.0 |
| Pomegranate | 50 | 1.0 |
| Potato | 50 | 1.0 |
| Sandwich | 50 | 1.0 |
| Strawberry | 50 | 1.0 |
| Taco | 50 | 1.0 |
| Taquito | 50 | 1.0 |
| Tomato | 50 | 1.0 |

## Validation results (best checkpoint; validation data guided checkpoint selection)

### Subset: all (n=480)

accuracy 0.7333 | macro precision 0.7294 | macro recall 0.7333 | macro F1 0.7240 | weighted F1 0.7240 | top-3 0.9000 | log loss 0.9100

Weakest 8 classes by F1:

| class_id | food | support | precision | recall | f1 |
| --- | --- | --- | --- | --- | --- |
| 21 | Taco | 20 | 0.1667 | 0.1 | 0.125 |
| 22 | Taquito | 20 | 0.5455 | 0.3 | 0.3871 |
| 1 | Baked Potato | 20 | 0.5556 | 0.5 | 0.5263 |
| 19 | Sandwich | 20 | 0.5 | 0.65 | 0.5652 |
| 6 | Crispy Chicken | 20 | 0.6667 | 0.6 | 0.6316 |
| 18 | Potato | 20 | 0.75 | 0.6 | 0.6667 |
| 15 | Orange | 20 | 0.75 | 0.6 | 0.6667 |
| 23 | Tomato | 20 | 0.6842 | 0.65 | 0.6667 |

Most frequent confusions:

| true | predicted_as | images |
| --- | --- | --- |
| Sandwich | Burger | 5 |
| Taquito | Sandwich | 4 |
| Taco | Taquito | 4 |
| Taquito | Taco | 4 |
| Baked Potato | Pizza | 4 |
| Potato | Mango | 3 |
| Taco | Sandwich | 3 |
| Taco | Pizza | 3 |
| Guava | Pomegranate | 3 |
| Crispy Chicken | Taco | 3 |


### Subset: original_only (n=442)

accuracy 0.7308 | macro precision 0.7185 | macro recall 0.7234 | macro F1 0.7109 | weighted F1 0.7206 | top-3 0.8937 | log loss 0.9297

Weakest 8 classes by F1:

| class_id | food | support | precision | recall | f1 |
| --- | --- | --- | --- | --- | --- |
| 21 | Taco | 20 | 0.1667 | 0.1 | 0.125 |
| 22 | Taquito | 20 | 0.5455 | 0.3 | 0.3871 |
| 1 | Baked Potato | 20 | 0.5556 | 0.5 | 0.5263 |
| 0 | Apple | 4 | 0.4286 | 0.75 | 0.5455 |
| 15 | Orange | 13 | 0.75 | 0.4615 | 0.5714 |
| 19 | Sandwich | 20 | 0.52 | 0.65 | 0.5778 |
| 6 | Crispy Chicken | 20 | 0.6667 | 0.6 | 0.6316 |
| 2 | Banana | 5 | 0.75 | 0.6 | 0.6667 |

Most frequent confusions:

| true | predicted_as | images |
| --- | --- | --- |
| Sandwich | Burger | 5 |
| Taquito | Taco | 4 |
| Taco | Taquito | 4 |
| Taquito | Sandwich | 4 |
| Baked Potato | Pizza | 4 |
| Potato | Mango | 3 |
| Taco | Sandwich | 3 |
| Taco | Pizza | 3 |
| Guava | Pomegranate | 3 |
| Crispy Chicken | Taco | 3 |


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
