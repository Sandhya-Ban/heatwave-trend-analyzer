"""Heatwave definition and per-year aggregation.

Definition (documented in README):
  * For every calendar day d, threshold(d) = P-th percentile (default 95) of daily Tmax over all
    baseline years, pooling a +/-7 day window around d (15 days x N years samples). This respects
    seasonality: a "hot" January day is hot *for January*.
  * A heatwave is >= `min_days` (default 3) consecutive days with Tmax > threshold(d).
  * A missing/invalid day is NOT hot, so it ends a run (we never invent exceedances in gaps).
  * An event belongs to the year in which it starts.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

ALGO_VERSION = "2.0"
MIN_YEAR_COVERAGE = 0.9   # a year with < 90% valid days is excluded from trend statistics


@dataclass(frozen=True)
class HeatwaveParams:
    percentile: float = 95.0
    min_days: int = 3
    half_window: int = 7
    min_samples: int = 30


def doy366(index: pd.DatetimeIndex) -> np.ndarray:
    """0-based day-of-year on a 366-day calendar so Mar 1 is always index 60, leap year or not."""
    doy = index.dayofyear.to_numpy()
    shift = (~index.is_leap_year) & (index.month > 2)
    return np.where(shift, doy + 1, doy) - 1


def compute_thresholds(series: pd.Series, p: HeatwaveParams) -> np.ndarray:
    """Array of 366 thresholds (NaN where fewer than min_samples valid baseline values exist)."""
    years = series.index.year
    uy = np.unique(years)
    mat = np.full((len(uy), 366), np.nan)
    mat[np.searchsorted(uy, years), doy366(series.index)] = series.to_numpy(dtype=float)
    w = p.half_window
    padded = np.concatenate([mat[:, -w:], mat, mat[:, :w]], axis=1)   # circular year wrap
    thr = np.full(366, np.nan)
    for d in range(366):
        pool = padded[:, d:d + 2 * w + 1].ravel()
        pool = pool[~np.isnan(pool)]
        if pool.size >= p.min_samples:
            thr[d] = np.percentile(pool, p.percentile)
    return thr


def detect_heatwaves(series: pd.Series, thr_by_doy: np.ndarray, p: HeatwaveParams) -> list[dict]:
    vals = series.to_numpy(dtype=float)
    thr = thr_by_doy[doy366(series.index)]
    with np.errstate(invalid="ignore"):
        hot = vals > thr                      # NaN comparisons are False -> gaps break runs
    padded = np.concatenate([[0], hot.astype(np.int8), [0]])
    d = np.diff(padded)
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]   # ends are exclusive
    events = []
    for s, e in zip(starts, ends):
        if e - s < p.min_days:
            continue
        excess = vals[s:e] - thr[s:e]
        events.append({
            "start": series.index[s].date().isoformat(),
            "end": series.index[e - 1].date().isoformat(),
            "year": int(series.index[s].year),
            "duration_days": int(e - s),
            "peak_tmax_c": round(float(vals[s:e].max()), 1),
            "mean_excess_c": round(float(excess.mean()), 2),
            "max_excess_c": round(float(excess.max()), 2),
        })
    return events


def yearly_metrics(series: pd.Series, events: list[dict], start_year: int, end_year: int) -> list[dict]:
    by_year: dict[int, list[dict]] = {}
    for ev in events:
        by_year.setdefault(ev["year"], []).append(ev)
    rows = []
    for y in range(start_year, end_year + 1):
        ys = series[series.index.year == y]
        full_len = 366 if pd.Timestamp(year=y, month=1, day=1).is_leap_year else 365
        n_idx = len(ys)
        valid = int(ys.notna().sum())
        coverage = valid / n_idx if n_idx else 0.0
        reliable = n_idx >= MIN_YEAR_COVERAGE * full_len and coverage >= MIN_YEAR_COVERAGE
        evs = by_year.get(y, [])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mean_tmax = float(np.nanmean(ys.to_numpy())) if valid else None
        durs = [e["duration_days"] for e in evs]
        rows.append({
            "year": y,
            "days_in_data": n_idx, "valid_days": valid, "coverage": round(coverage, 3),
            "reliable": bool(reliable),
            "events": len(evs),
            "heatwave_days": int(sum(durs)),
            "max_duration": int(max(durs)) if durs else 0,
            "mean_duration": round(float(np.mean(durs)), 2) if durs else None,
            "mean_intensity_c": round(float(np.mean([e["mean_excess_c"] for e in evs])), 2) if evs else None,
            "max_intensity_c": round(float(max(e["max_excess_c"] for e in evs)), 2) if evs else None,
            "mean_tmax_c": round(mean_tmax, 2) if mean_tmax is not None else None,
        })
    return rows


def add_rolling(rows: list[dict], keys=("events", "heatwave_days"), window: int = 5) -> None:
    """Centered rolling mean over *reliable* years only (unreliable years are skipped, not zero)."""
    for k in keys:
        s = pd.Series([r[k] if r["reliable"] else np.nan for r in rows], dtype=float)
        rm = s.rolling(window, center=True, min_periods=3).mean()
        for r, v in zip(rows, rm):
            r[f"{k}_rolling{window}"] = None if np.isnan(v) else round(float(v), 3)
