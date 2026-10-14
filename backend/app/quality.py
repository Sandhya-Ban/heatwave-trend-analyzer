"""Turn a raw provider series into a clean, gap-aware daily pandas Series."""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from .errors import DataQualityError

PLAUSIBLE_MIN_C = -90.0   # coldest ever recorded: -89.2 C
PLAUSIBLE_MAX_C = 60.0    # hottest ever recorded: ~56.7 C
PLAUSIBLE_MAX_PRECIP_MM = 2000.0   # world record is ~1,825 mm in a day
MIN_OVERALL_COVERAGE = 0.5


@dataclass
class QualityReport:
    total_days: int
    valid_days: int
    missing_days: int
    outliers_removed: int
    duplicate_dates_dropped: int
    unparseable_dates_dropped: int
    unit_converted_from: str | None
    coverage: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["coverage"] = round(d["coverage"], 4)
        return d


def _to_celsius(vals: np.ndarray, units: str) -> tuple[np.ndarray, str | None]:
    u = (units or "").strip().lower().replace("°", "").replace("º", "")
    if u in ("", "c", "celsius", "degc"):
        return vals, None
    if u in ("f", "fahrenheit", "degf"):
        return (vals - 32.0) * 5.0 / 9.0, "°F"
    if u in ("k", "kelvin"):
        return vals - 273.15, "K"
    raise DataQualityError(f"unrecognised temperature unit '{units}'")


def _to_mm(vals: np.ndarray, units: str) -> tuple[np.ndarray, str | None]:
    u = (units or "").strip().lower()
    if u in ("", "mm", "millimeter", "millimeters"):
        return vals, None
    if u in ("inch", "in", "inches"):
        return vals * 25.4, "inch"
    raise DataQualityError(f"unrecognised precipitation unit '{units}'")


def clean_series(dates, values, units: str = "°C", kind: str = "tmax") -> tuple[pd.Series, QualityReport]:
    """Returns (daily Series indexed by date, NaN = unusable day, report)."""
    if len(dates) != len(values):
        raise DataQualityError("dates and values differ in length")
    idx = pd.to_datetime(pd.Series(list(dates), dtype="object"), errors="coerce", utc=False)
    vals = pd.to_numeric(pd.Series(list(values), dtype="object"), errors="coerce").astype(float)
    bad_dates = int(idx.isna().sum())
    df = pd.DataFrame({"d": idx, "v": vals.values}).dropna(subset=["d"])
    if df.empty:
        raise DataQualityError("no parseable dates in data")
    df["d"] = df["d"].dt.tz_localize(None).dt.normalize() if df["d"].dt.tz is not None else df["d"].dt.normalize()
    n_dupes = int(df["d"].duplicated().sum())
    df = df.drop_duplicates("d", keep="first").sort_values("d")

    v = df["v"].to_numpy(dtype=float)
    v[~np.isfinite(v)] = np.nan
    if kind == "precip":
        v, converted = _to_mm(v, units)
        v[(v < 0) & (v > -0.05)] = 0.0                     # tiny negative float noise is zero rain
        out_mask = np.isfinite(v) & ((v < 0) | (v > PLAUSIBLE_MAX_PRECIP_MM))
    else:
        v, converted = _to_celsius(v, units)
        out_mask = np.isfinite(v) & ((v < PLAUSIBLE_MIN_C) | (v > PLAUSIBLE_MAX_C))
    v[out_mask] = np.nan

    s = pd.Series(v, index=pd.DatetimeIndex(df["d"]))
    full = pd.date_range(s.index[0], s.index[-1], freq="D")
    s = s.reindex(full)                      # days absent from the feed become explicit NaN gaps
    valid = int(s.notna().sum())
    cov = valid / len(s)
    if cov < MIN_OVERALL_COVERAGE:
        raise DataQualityError(f"only {cov:.0%} of days have usable data; cannot analyse this location/range")
    return s, QualityReport(len(s), valid, len(s) - valid, int(out_mask.sum()), n_dupes, bad_dates, converted, cov)
