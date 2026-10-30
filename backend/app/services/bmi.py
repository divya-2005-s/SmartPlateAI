"""BMI calculation and interpretation. BMI is a screening measure, not a diagnosis."""
from __future__ import annotations

ADULT_AGE = 20  # WHO/CDC: BMI-for-age percentiles are used below 20 years
WHO_CATEGORIES = [(18.5, "Underweight"), (25.0, "Healthy weight"), (30.0, "Overweight"), (35.0, "Obesity class I"),
                  (40.0, "Obesity class II"), (float("inf"), "Obesity class III")]
# Indian consensus guidelines (Misra et al., 2009) for Asian Indian adults.
INDIAN_CATEGORIES = [(18.0, "Underweight"), (23.0, "Normal"), (25.0, "Overweight"), (float("inf"), "Obesity")]


class BMIError(ValueError):
    pass


def to_metric(height_cm: float | None = None, weight_kg: float | None = None, height_ft: float | None = None,
              height_in: float | None = None, weight_lb: float | None = None) -> tuple[float, float]:
    if height_cm is None and (height_ft is not None or height_in is not None):
        height_cm = ((height_ft or 0) * 12 + (height_in or 0)) * 2.54
    if weight_kg is None and weight_lb is not None:
        weight_kg = weight_lb * 0.45359237
    if height_cm is None or weight_kg is None:
        raise BMIError("Enter both height and weight.")
    if not 50 <= height_cm <= 260:
        raise BMIError("Height must be between 50 and 260 cm (about 1 ft 8 in to 8 ft 6 in).")
    if not 2 <= weight_kg <= 400:
        raise BMIError("Weight must be between 2 and 400 kg.")
    return height_cm, weight_kg


def _band(bmi: float, table: list[tuple[float, str]]) -> str:
    return next(label for upper, label in table if bmi < upper)


def calculate(height_cm: float, weight_kg: float, age: int | None = None) -> dict:
    m = height_cm / 100.0
    bmi = round(weight_kg / (m * m), 1)
    healthy = (round(18.5 * m * m, 1), round(24.9 * m * m, 1))
    out = {"bmi": bmi, "height_cm": round(height_cm, 1), "weight_kg": round(weight_kg, 1), "age": age,
           "disclaimer": "BMI is a screening measure, not a diagnosis. It does not measure body fat directly and can be misleading "
                         "for athletes, older adults, and during pregnancy. Talk to a doctor for personal advice."}
    if age is not None and age < ADULT_AGE:
        out.update(category=None, adult_categories_apply=False,
                   interpretation="For children and teenagers (under 20), BMI must be compared with age- and sex-specific growth "
                                  "charts (BMI-for-age percentiles). Adult categories do not apply, so no category is shown.")
        return out
    out.update(category=_band(bmi, WHO_CATEGORIES), adult_categories_apply=True,
               indian_category=_band(bmi, INDIAN_CATEGORIES),
               healthy_weight_range_kg=healthy,
               interpretation=f"A BMI of {bmi} is in the WHO '{_band(bmi, WHO_CATEGORIES)}' range for adults.",
               note_asian_indian="For Asian Indian adults, Indian consensus guidelines (2009) use lower cut-offs: overweight from 23 "
                                 "and obesity from 25, because health risks rise at a lower BMI.")
    if age is None:
        out["age_note"] = "Age was not given; adult categories are shown and apply from age 20."
    return out
