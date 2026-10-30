# Non-food rejection calibration report

Model run: `food_classifier` | generated 2026-10-11 21:09:10 | seed 42

## Thresholds

```json
{
  "food_mass_low": 0.029811055585741996,
  "maha_high": 2477.418636746965,
  "conf_min": 0.573834879398346,
  "margin_min": 0.24351972714066508
}
```

Gate method: grid search on calibration negatives (false-reject <= 2%). Confidence/margin: target accuracy of accepted predictions 95% (met); coverage on calibration data 0.937.

## Valid foods (validation, evaluation half - not used to choose thresholds)

- images: 3,775
- accepted: 3406/3775 = 90.2% (95% CI 89.2%-91.1%)
- wrongly rejected as NON_FOOD: 51/3775 = 1.4% (95% CI 1.0%-1.8%)
- UNSUPPORTED_FOOD: 111/3775 = 2.9% (95% CI 2.4%-3.5%)
- LOW_CONFIDENCE: 207/3775 = 5.5% (95% CI 4.8%-6.3%)
- accuracy among accepted: 0.9568408690546095
- accuracy over all images (no rejection): 0.926092715231788

## Non-food images (evaluation half)

- **packaging** (n=124): rejected as NON_FOOD 59/124 = 47.6% (95% CI 39.0%-56.3%); not accepted as a food (any rejection) 98/124 = 79.0% (95% CI 71.0%-85.3%); wrongly accepted as food 26/124 = 21.0% (95% CI 14.7%-29.0%)

## Limitations

- Non-food rejection was only evaluated on the negative examples listed above. Categories or conditions not represented there are untested.
- Food that is not one of the 24 supported foods (sushi, curry, ...) may be answered with UNSUPPORTED_FOOD or LOW_CONFIDENCE, not a food name.
- Packaging photos, empty plates and food drawings can look food-like to the ImageNet signal; see the 'hard' and 'packaging' rows.
- Thresholds guarantee nothing for a single photo; rates are estimates from finite samples (95% Wilson intervals shown).
