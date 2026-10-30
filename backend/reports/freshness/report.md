# Freshness head

```json
{
  "food_model_sha256": "d1d90d1053634f8148b3584c502538ff10624eeeda9e1f05c235a570e72ec5b8",
  "supported_foods": [
    "Apple",
    "Banana",
    "Bell Pepper",
    "Carrot",
    "Cucumber",
    "Grape",
    "Guava",
    "Jujube",
    "Mango",
    "Orange",
    "Pomegranate",
    "Potato",
    "Strawberry",
    "Tomato"
  ],
  "t_fresh": 0.47130000000000005,
  "t_spoiled": 0.471302,
  "validation": {
    "t_spoiled": 0.471302,
    "t_fresh": 0.47130000000000005,
    "target_precision": 0.9,
    "precision_spoiled": 0.9543568464730291,
    "precision_fresh": 0.9515384615384616,
    "coverage": 1.0,
    "n": 2505,
    "accuracy_at_0.5": 0.9512974051896208,
    "per_food": {
      "Apple": {
        "n": 159,
        "accuracy_at_0.5": 0.9622641509433962
      },
      "Banana": {
        "n": 211,
        "accuracy_at_0.5": 0.9620853080568721
      },
      "Bell Pepper": {
        "n": 172,
        "accuracy_at_0.5": 0.9244186046511628
      },
      "Carrot": {
        "n": 168,
        "accuracy_at_0.5": 0.9285714285714286
      },
      "Cucumber": {
        "n": 176,
        "accuracy_at_0.5": 0.9715909090909091
      },
      "Grape": {
        "n": 60,
        "accuracy_at_0.5": 0.85
      },
      "Guava": {
        "n": 60,
        "accuracy_at_0.5": 0.95
      },
      "Jujube": {
        "n": 60,
        "accuracy_at_0.5": 0.8833333333333333
      },
      "Mango": {
        "n": 480,
        "accuracy_at_0.5": 0.9729166666666667
      },
      "Orange": {
        "n": 159,
        "accuracy_at_0.5": 0.9371069182389937
      },
      "Pomegranate": {
        "n": 60,
        "accuracy_at_0.5": 0.9333333333333333
      },
      "Potato": {
        "n": 176,
        "accuracy_at_0.5": 0.8693181818181818
      },
      "Strawberry": {
        "n": 388,
        "accuracy_at_0.5": 0.9845360824742269
      },
      "Tomato": {
        "n": 176,
        "accuracy_at_0.5": 0.9829545454545454
      }
    }
  },
  "trained_on": {
    "train_images": 11880,
    "val_images": 2505
  },
  "created": "2026-10-15T22:44:24",
  "note": "Thresholds chosen on the validation split; the test split was not used."
}
```
