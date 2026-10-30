"""Pure-logic tests: rejection decisions, feature statistics, thresholds. No TensorFlow or FastAPI needed."""
import numpy as np
import pytest

from app.ml.rejection import (Thresholds, choose_conf_margin, choose_gate_thresholds, decide_batch, fit_feature_stats,
                              min_mahalanobis, wilson_interval)

TH = Thresholds(food_mass_low=0.2, maha_high=100.0, conf_min=0.6, margin_min=0.2)


def probs(top, second=0.05, k=4):
    p = np.full(k, (1 - top - second) / (k - 2))
    p[0], p[1] = top, second
    return p


def test_confident_softmax_alone_never_means_food():
    """A 0.99 softmax on an image that is far from every food AND has no ImageNet food mass is rejected as non-food."""
    d = decide_batch(np.array([probs(0.99)]), np.array([500.0]), np.array([0.01]), TH)
    assert d[0] == "non_food"


def test_valid_food_accepted():
    assert decide_batch(np.array([probs(0.9)]), np.array([40.0]), np.array([0.7]), TH)[0] == "accept"


def test_far_but_food_like_is_unsupported_not_non_food():
    assert decide_batch(np.array([probs(0.9)]), np.array([500.0]), np.array([0.7]), TH)[0] == "unsupported_food"


def test_low_confidence_and_low_margin_are_uncertain():
    assert decide_batch(np.array([probs(0.4, 0.3)]), np.array([40.0]), np.array([0.7]), TH)[0] == "uncertain"
    assert decide_batch(np.array([probs(0.65, 0.6)]), np.array([40.0]), np.array([0.7]), TH)[0] == "uncertain"


def test_feature_distance_separates_clusters():
    rng = np.random.default_rng(0)
    K, D = 5, 30
    centres = rng.normal(0, 3, (K, D))
    y = rng.integers(0, K, 2000)
    means, prec = fit_feature_stats(centres[y] + rng.normal(0, 1, (2000, D)), y, K)
    inliers = min_mahalanobis(centres[rng.integers(0, K, 500)] + rng.normal(0, 1, (500, D)), means, prec)
    outliers = min_mahalanobis(rng.normal(0, 8, (500, D)), means, prec)
    assert np.median(outliers) > 5 * np.median(inliers)


def test_fit_requires_every_class():
    with pytest.raises(ValueError):
        fit_feature_stats(np.zeros((4, 3)), np.array([0, 0, 1, 1]), 3)


def test_positive_only_thresholds_keep_false_rejection_small():
    rng = np.random.default_rng(1)
    fm, md = rng.beta(5, 2, 4000), rng.chisquare(30, 4000)
    g = choose_gate_thresholds(fm, md)
    assert g["false_reject_calib"] <= 0.02 and g["neg_reject_calib"] is None


def test_negatives_improve_rejection_within_false_reject_budget():
    rng = np.random.default_rng(2)
    fm, md = rng.beta(5, 2, 4000), rng.chisquare(30, 4000)
    nfm, nmd = rng.beta(1, 10, 300), rng.chisquare(30, 300) * 6
    g = choose_gate_thresholds(fm, md, nfm, nmd, 0.02)
    assert g["false_reject_calib"] <= 0.02 and g["neg_reject_calib"] > 0.8


def test_conf_margin_meets_target_when_possible():
    rng = np.random.default_rng(3)
    conf = rng.uniform(0.3, 1, 3000)
    correct = rng.uniform(0, 1, 3000) < conf          # higher confidence -> more often correct
    r = choose_conf_margin(conf, conf - rng.uniform(0, 0.3, 3000), correct, 0.9)
    assert r["target_met"] and r["accuracy_of_accepted"] >= 0.9


def test_wilson_interval():
    lo, hi = wilson_interval(0, 100)
    assert lo == 0.0 and 0.03 < hi < 0.05
    assert np.isnan(wilson_interval(0, 0)[0])