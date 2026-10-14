"""Heavy-rainfall and drought definitions (precipitation-based hazards).

Heavy rainfall (ETCCDI R95p-style): a *wet day* has >= 1 mm. The threshold is the P-th percentile
(default 95) of wet-day totals over the selected period; a heavy-rain day exceeds it.
(One threshold for the whole year - wet-day samples are too sparse for a per-calendar-day percentile.)

Drought: 3-month Standardized Precipitation Index (SPI-3). Monthly totals -> rolling 3-month sums ->
for each calendar month a gamma distribution (with a zero-rain probability mass) is fitted over the
selected period and transformed to a standard normal. A drought month has SPI-3 <= -1. A drought event
is >= 2 consecutive drought months. Months with <90% valid days are treated as missing and break events.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sps

from .errors import DataQualityError
from .hazards import MIN_YEAR_COVERAGE

WET_MM = 1.0
SPI_THRESHOLD = -1.0
MIN_DROUGHT_MONTHS = 2
MIN_WET_DAYS = 50
MIN_SPI_SAMPLES = 10


def _year_info(series: pd.Series, y: int):
    ys = series[series.index.year == y]
    full = 366 if pd.Timestamp(year=y, month=1, day=1).is_leap_year else 365
    n, valid = len(ys), int(ys.notna().sum())
    cov = valid / n if n else 0.0
    return ys, n, valid, cov, bool(n >= MIN_YEAR_COVERAGE * full and cov >= MIN_YEAR_COVERAGE)


def _annual_total(ys: pd.Series, valid: int, cov: float):
    return round(float(np.nansum(ys.to_numpy()) / cov), 1) if valid and cov > 0 else None


def heavy_rain(series: pd.Series, percentile: float, start_year: int, end_year: int):
    v = series.to_numpy(dtype=float)
    wet = v[np.isfinite(v) & (v >= WET_MM)]
    if wet.size < MIN_WET_DAYS:
        raise DataQualityError(f"only {wet.size} wet days in this period; too few to define heavy rainfall")
    thr = float(np.percentile(wet, percentile))
    with np.errstate(invalid="ignore"):
        idx = np.where(v > thr)[0]
    events = []
    for i in idx:
        d = series.index[i].date().isoformat()
        events.append({"start": d, "end": d, "year": int(series.index[i].year),
                       "precip_mm": round(float(v[i]), 1), "excess_mm": round(float(v[i] - thr), 1)})
    by_year: dict[int, list] = {}
    for e in events:
        by_year.setdefault(e["year"], []).append(e)
    rows = []
    for y in range(start_year, end_year + 1):
        ys, n, valid, cov, rel = _year_info(series, y)
        evs = by_year.get(y, [])
        rows.append({
            "year": y, "days_in_data": n, "valid_days": valid, "coverage": round(cov, 3), "reliable": rel,
            "events": len(evs),
            "rx1day_mm": round(float(np.nanmax(ys.to_numpy())), 1) if valid else None,
            "heavy_total_mm": round(sum(e["precip_mm"] for e in evs), 1),
            "annual_total_mm": _annual_total(ys, valid, cov),
        })
    summary = {"threshold_mm": round(thr, 1), "wet_days": int(wet.size), "wet_day_mm": WET_MM}
    return events, rows, summary


def spi3(series: pd.Series) -> pd.Series:
    """Monthly SPI-3 indexed by month start. NaN where it cannot be computed."""
    g = series.resample("MS")
    total = g.sum(min_count=1)
    count = g.count()
    expected = total.index.days_in_month
    total[count.to_numpy() < MIN_YEAR_COVERAGE * expected] = np.nan      # incomplete / partial months
    roll = total.rolling(3).sum()                                          # NaN if any month missing
    out = pd.Series(np.nan, index=roll.index)
    for m in range(1, 13):
        sel = roll.index.month == m
        x = roll[sel].dropna()
        if len(x) < MIN_SPI_SAMPLES:
            continue
        q = float((x == 0).mean())
        pos = x[x > 0].to_numpy()
        if len(pos) < 5 or np.ptp(pos) == 0:
            continue
        a, loc, scale = sps.gamma.fit(pos, floc=0)
        h = q + (1 - q) * sps.gamma.cdf(x.to_numpy(), a, loc=0, scale=scale)
        out.loc[x.index] = sps.norm.ppf(np.clip(h, 1e-6, 1 - 1e-6))
    return out


def drought(series: pd.Series, start_year: int, end_year: int):
    spi = spi3(series)
    dry = (spi <= SPI_THRESHOLD).to_numpy()
    padded = np.concatenate([[0], dry.astype(np.int8), [0]])
    d = np.diff(padded)
    events = []
    for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
        if e - s < MIN_DROUGHT_MONTHS:
            continue
        start, end = spi.index[s], spi.index[e - 1]
        events.append({"start": start.date().isoformat(),
                       "end": (end + pd.offsets.MonthEnd(0)).date().isoformat(),
                       "year": int(start.year), "duration_months": int(e - s),
                       "min_spi": round(float(spi.iloc[s:e].min()), 2)})
    drought_months = pd.Series(0, index=spi.index)
    for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
        if e - s >= MIN_DROUGHT_MONTHS:
            drought_months.iloc[s:e] = 1
    by_year: dict[int, list] = {}
    for ev in events:
        by_year.setdefault(ev["year"], []).append(ev)
    rows = []
    for y in range(start_year, end_year + 1):
        ys, n, valid, cov, rel = _year_info(series, y)
        in_y = spi.index.year == y
        evs = by_year.get(y, [])
        ymin = spi[in_y].min() if in_y.any() else np.nan
        rows.append({
            "year": y, "days_in_data": n, "valid_days": valid, "coverage": round(cov, 3), "reliable": rel,
            "events": len(evs),
            "drought_months": int(drought_months[in_y].sum()),
            "max_duration": max((e["duration_months"] for e in evs), default=0),
            "min_spi": None if np.isnan(ymin) else round(float(ymin), 2),
            "annual_total_mm": _annual_total(ys, valid, cov),
        })
    summary = {"spi_threshold": SPI_THRESHOLD, "months_with_spi": int(spi.notna().sum())}
    if summary["months_with_spi"] < 24:
        raise DataQualityError("not enough complete months to compute the drought index")
    return events, rows, summary
