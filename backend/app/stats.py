"""Trend statistics: OLS regression + Mann-Kendall with Sen's slope."""
from __future__ import annotations

import math

import numpy as np
from scipy import stats as sps

MIN_POINTS = 10
ALPHA = 0.05


def mann_kendall(x, y) -> dict:
    """Non-parametric trend test (tie-corrected normal approximation). x strictly increasing."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    n = len(y)
    s = 0
    slopes = []
    for i in range(n - 1):
        d = y[i + 1:] - y[i]
        s += int(np.sign(d).sum())
        slopes.extend((d / (x[i + 1:] - x[i])).tolist())
    _, counts = np.unique(y, return_counts=True)
    tie = sum(int(t) * (int(t) - 1) * (2 * int(t) + 5) for t in counts if t > 1)
    var = (n * (n - 1) * (2 * n + 5) - tie) / 18.0
    if var <= 0:
        z, p = 0.0, 1.0
    else:
        z = (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var) if s < 0 else 0.0
        p = float(2 * (1 - sps.norm.cdf(abs(z))))
    return {"S": s, "z": z, "p_value": p, "tau": s / (n * (n - 1) / 2), "sen_slope": float(np.median(slopes))}


def analyze_trend(years, values, alpha: float = ALPHA) -> dict:
    x = np.asarray(years, float)
    y = np.asarray(values, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    n = len(y)
    if n < MIN_POINTS:
        return {"status": "insufficient_data", "n": n, "min_required": MIN_POINTS}

    if np.ptp(y) == 0:
        slope, icpt, r2, p_ols = 0.0, float(y[0]), 0.0, 1.0
    else:
        lr = sps.linregress(x, y)
        slope, icpt, r2, p_ols = float(lr.slope), float(lr.intercept), float(lr.rvalue ** 2), float(lr.pvalue)
    mk = mann_kendall(x, y)

    k = 10 if n >= 20 else n // 2
    early, late = y[:k], y[-k:]
    em, lm = float(early.mean()), float(late.mean())
    if mk["p_value"] < alpha:
        direction = "increasing" if mk["tau"] > 0 else "decreasing"
    else:
        direction = "no_significant_trend"
    return {
        "status": "ok", "n": n, "alpha": alpha, "direction": direction,
        "significant": mk["p_value"] < alpha,
        "ols": {"slope_per_decade": slope * 10, "intercept": icpt, "r2": r2, "p_value": p_ols,
                "fit_first": icpt + slope * x[0], "fit_last": icpt + slope * x[-1]},
        "mann_kendall": {"tau": mk["tau"], "z": mk["z"], "p_value": mk["p_value"],
                         "sen_slope_per_decade": mk["sen_slope"] * 10},
        "comparison": {"early_years": [int(x[0]), int(x[k - 1])], "late_years": [int(x[-k]), int(x[-1])],
                       "early_mean": em, "late_mean": lm, "abs_change": lm - em,
                       "pct_change": ((lm - em) / em * 100.0) if em > 0 else None},
    }
