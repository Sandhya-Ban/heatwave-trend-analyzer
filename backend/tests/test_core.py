import numpy as np
import pandas as pd
import pytest

from app import hazards
from app.errors import DataQualityError
from app.quality import clean_series
from app.stats import analyze_trend, mann_kendall

P = hazards.HeatwaveParams(percentile=95, min_days=3)


def mk_series(start="2000-01-01", end="2019-12-31", base=20.0, seed=0, noise=1.0):
    idx = pd.date_range(start, end, freq="D")
    rng = np.random.default_rng(seed)
    return pd.Series(base + rng.normal(0, noise, len(idx)), index=idx)


# ---------- quality ----------
def test_clean_handles_gaps_dupes_outliers_strings():
    dates = ["2020-01-01", "2020-01-02", "2020-01-02", "2020-01-03", "2020-01-04", "bad-date", "2020-01-05", "2020-01-06", "2020-01-08"]
    vals = [10, None, 11, 9, "abc", 12, 999, 8, 7]
    s, q = clean_series(dates, vals, "°C")
    assert len(s) == 8 and s.index[0] == pd.Timestamp("2020-01-01") and s.index[-1] == pd.Timestamp("2020-01-08")
    assert q.duplicate_dates_dropped == 1 and q.unparseable_dates_dropped == 1 and q.outliers_removed == 1
    assert s["2020-01-07"] != s["2020-01-07"]          # day absent from feed -> explicit NaN gap
    assert s["2020-01-04"] != s["2020-01-04"]          # non-numeric -> NaN
    assert s["2020-01-05"] != s["2020-01-05"]          # 999 outlier -> NaN
    assert s["2020-01-02"] != s["2020-01-02"]          # first duplicate (None) kept: deterministic
    assert s["2020-01-03"] == 9 and q.valid_days == 4


def test_clean_unit_conversion_and_unknown_unit():
    s, q = clean_series(["2020-01-01", "2020-01-02"], [104.0, 32.0], "°F")
    assert s.iloc[0] == pytest.approx(40.0) and q.unit_converted_from == "°F"
    s, _ = clean_series(["2020-01-01", "2020-01-02"], [300.15, 273.15], "K")
    assert s.iloc[0] == pytest.approx(27.0)
    with pytest.raises(DataQualityError):
        clean_series(["2020-01-01"], [1], "parsecs")


def test_clean_rejects_mostly_empty():
    with pytest.raises(DataQualityError):
        clean_series(["2020-01-01", "2020-01-02", "2020-01-03"], [None, None, 5], "°C")


def test_clean_unsorted_input():
    s, _ = clean_series(["2020-01-03", "2020-01-01", "2020-01-02"], [3, 1, 2])
    assert list(s.values) == [1, 2, 3]


# ---------- hazard logic ----------
def test_doy366_leap_alignment():
    a = hazards.doy366(pd.DatetimeIndex(["2019-03-01", "2020-03-01", "2020-02-29", "2019-12-31", "2020-12-31"]))
    assert list(a) == [60, 60, 59, 365, 365]


def test_threshold_matches_percentile_for_constant_distribution():
    idx = pd.date_range("2000-01-01", "2019-12-31", freq="D")
    s = pd.Series(np.tile(np.arange(100.0), len(idx) // 100 + 1)[: len(idx)], index=idx)
    thr = hazards.compute_thresholds(s, P)
    assert np.nanmin(thr) > 85 and np.nanmax(thr) <= 99


def test_detects_exact_run_lengths_and_ignores_two_day_runs():
    s = mk_series(noise=0.5)
    thr = hazards.compute_thresholds(s, P)
    s2 = s.copy()
    hot = lambda d: thr[hazards.doy366(pd.DatetimeIndex([d]))[0]] + 5
    for d in pd.date_range("2010-07-10", periods=4): s2[d] = hot(d)      # 4-day event
    for d in pd.date_range("2012-07-10", periods=2): s2[d] = hot(d)      # only 2 days -> not an event
    for d in pd.date_range("2014-07-10", periods=3): s2[d] = hot(d)      # exactly 3 -> event
    evs = [e for e in hazards.detect_heatwaves(s2, thr, P) if e["start"] in ("2010-07-10", "2012-07-10", "2014-07-10")]
    assert {(e["start"], e["duration_days"]) for e in evs} == {("2010-07-10", 4), ("2014-07-10", 3)}


def test_nan_gap_breaks_a_run():
    s = mk_series(noise=0.5)
    thr = hazards.compute_thresholds(s, P)
    s2 = s.copy()
    days = pd.date_range("2011-07-10", periods=5)
    for d in days: s2[d] = 80 if False else thr[hazards.doy366(pd.DatetimeIndex([d]))[0]] + 5
    s2[days[2]] = np.nan                                               # 2 + gap + 2 => no event
    evs = [e for e in hazards.detect_heatwaves(s2, thr, P) if e["start"].startswith("2011-07")]
    assert evs == []


def test_event_at_series_end_and_year_boundary_assignment():
    s = mk_series(noise=0.5)
    thr = hazards.compute_thresholds(s, P)
    s2 = s.copy()
    for d in pd.date_range("2019-12-29", "2019-12-31"): s2[d] = thr[hazards.doy366(pd.DatetimeIndex([d]))[0]] + 4
    evs = hazards.detect_heatwaves(s2, thr, P)
    assert any(e["end"] == "2019-12-31" and e["year"] == 2019 for e in evs)
    cross = s.copy()
    for d in pd.date_range("2005-12-30", "2006-01-02"): cross[d] = thr[hazards.doy366(pd.DatetimeIndex([d]))[0]] + 4
    e = [e for e in hazards.detect_heatwaves(cross, thr, P) if e["start"] == "2005-12-30"][0]
    assert e["year"] == 2005 and e["duration_days"] == 4


def test_yearly_reliability_flags_partial_and_gappy_years():
    s = mk_series(start="2000-01-01", end="2019-06-30")
    s["2005-03-01":"2005-09-30"] = np.nan
    ev = hazards.detect_heatwaves(s, hazards.compute_thresholds(s, P), P)
    rows = hazards.yearly_metrics(s, ev, 2000, 2019)
    by = {r["year"]: r for r in rows}
    assert by[2019]["reliable"] is False and by[2005]["reliable"] is False and by[2010]["reliable"] is True
    assert sum(r["heatwave_days"] for r in rows) == sum(e["duration_days"] for e in ev)


def test_percentile_parameter_changes_event_counts():
    s = mk_series(seed=3)
    n95 = len(hazards.detect_heatwaves(s, hazards.compute_thresholds(s, P), P))
    p90 = hazards.HeatwaveParams(percentile=90, min_days=3)
    n90 = len(hazards.detect_heatwaves(s, hazards.compute_thresholds(s, p90), p90))
    assert n90 > n95 > 0


# ---------- stats ----------
def test_mann_kendall_monotonic_and_constant_and_ties():
    x = np.arange(2000, 2020)
    inc = mann_kendall(x, x - 2000)
    assert inc["p_value"] < 0.001 and inc["tau"] == pytest.approx(1.0) and inc["sen_slope"] == pytest.approx(1.0)
    const = analyze_trend(x, np.zeros(20))
    assert const["status"] == "ok" and not const["significant"] and const["comparison"]["pct_change"] is None
    zi = analyze_trend(x, [0, 0, 0, 1, 0, 0, 2, 0, 0, 0, 1, 0, 0, 0, 0, 3, 0, 0, 1, 0])  # zero-inflated counts
    assert zi["status"] == "ok" and 0 <= zi["mann_kendall"]["p_value"] <= 1


def test_trend_insufficient_and_nan_filtering():
    assert analyze_trend([2000, 2001], [1, 2])["status"] == "insufficient_data"
    r = analyze_trend(list(range(2000, 2015)), [np.nan] * 5 + list(range(10)))
    assert r["n"] == 10 and r["status"] == "ok"


def test_trend_detects_noisy_increase_and_pct_change():
    rng = np.random.default_rng(1)
    x = np.arange(1990, 2021)
    y = 2 + 0.3 * (x - 1990) + rng.normal(0, 1, len(x))
    r = analyze_trend(x, y)
    assert r["direction"] == "increasing" and r["significant"] and r["comparison"]["pct_change"] > 100
