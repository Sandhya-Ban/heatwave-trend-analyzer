import numpy as np
import pandas as pd
import pytest

from app import rainfall
from app.errors import DataQualityError
from app.quality import clean_series
from tests.test_api import Q, make


def rain(seed=0, start="1990-01-01", end="2019-12-31"):
    idx = pd.date_range(start, end, freq="D")
    r = np.random.default_rng(seed)
    wet = r.random(len(idx)) < 0.3
    return pd.Series(np.where(wet, r.gamma(0.8, 10, len(idx)), 0.0), index=idx)


def test_precip_cleaning_negative_outlier_inches_unknown():
    s, q = clean_series(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"], [0.0, -3.0, 99999, -0.01], "mm", kind="precip")
    assert q.outliers_removed == 2 and s.iloc[3] == 0.0 and np.isnan(s.iloc[1])
    s, q = clean_series(["2020-01-01", "2020-01-02"], [1.0, 2.0], "inch", kind="precip")
    assert s.iloc[0] == pytest.approx(25.4) and q.unit_converted_from == "inch"
    with pytest.raises(DataQualityError):
        clean_series(["2020-01-01"], [1], "furlongs", kind="precip")


def test_heavy_rain_threshold_and_events():
    s = rain()
    ev, rows, summ = rainfall.heavy_rain(s, 95, 1990, 2019)
    wet = s[s >= 1]
    assert summ["threshold_mm"] == pytest.approx(np.percentile(wet, 95), abs=0.06)
    assert all(e["precip_mm"] > summ["threshold_mm"] - 0.06 for e in ev)
    assert sum(r["events"] for r in rows) == len(ev) and len(rows) == 30
    ev90, _, _ = rainfall.heavy_rain(s, 90, 1990, 2019)
    assert len(ev90) > len(ev)


def test_heavy_rain_ignores_nan_and_requires_enough_wet_days():
    s = rain()
    s["1995-06-01":"1995-06-30"] = np.nan
    ev, rows, _ = rainfall.heavy_rain(s, 95, 1990, 2019)
    assert not any(e["start"].startswith("1995-06") for e in ev)
    with pytest.raises(DataQualityError):
        rainfall.heavy_rain(pd.Series(0.0, index=pd.date_range("2000-01-01", "2019-12-31")), 95, 2000, 2019)


def test_spi_is_roughly_standard_normal_and_flags_injected_drought():
    s = rain(seed=2)
    spi = rainfall.spi3(s).dropna()
    assert abs(spi.mean()) < 0.15 and 0.8 < spi.std() < 1.2
    dry = s.copy()
    dry["2005-03-01":"2005-08-31"] = 0.0                    # six rainless months
    ev, rows, _ = rainfall.drought(dry, 1990, 2019)
    assert any(e["start"].startswith("2005") and e["duration_months"] >= 2 for e in ev)
    assert all(e["end"] >= e["start"] for e in ev)
    assert sum(r["drought_months"] for r in rows) >= 4 and rows[15]["year"] == 2005 and rows[15]["drought_months"] >= 3


def test_spi_excludes_partial_and_gappy_months():
    s = rain(end="2019-06-15")
    s["2000-02-01":"2000-02-20"] = np.nan
    spi = rainfall.spi3(s)
    assert np.isnan(spi["2000-02-01"]) and np.isnan(spi["2000-03-01"]) and np.isnan(spi["2000-04-01"])   # 3-month window
    assert np.isnan(spi["2019-06-01"])                                                               # partial last month


def test_drought_too_little_data():
    with pytest.raises(DataQualityError):
        rainfall.drought(rain(start="2018-01-01", end="2019-12-31"), 2018, 2019)


def test_constant_rain_does_not_crash_spi():
    s = pd.Series(5.0, index=pd.date_range("1990-01-01", "2019-12-31"))
    spi = rainfall.spi3(s)                       # degenerate input: must not raise or return inf
    assert np.isfinite(spi.dropna()).all() and (spi.dropna() > -1).all()
    ev, _, _ = rainfall.drought(s, 1990, 2019)
    assert ev == []                              # no variability -> no drought flagged


# ---------- API ----------
@pytest.mark.parametrize("hz", ["heavy_rainfall", "drought"])
def test_api_each_hazard(hz):
    c, prov = make()
    r = c.get(f"/api/analysis?{Q}&hazard={hz}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["hazard"] == hz and len(d["yearly"]) == 30 and d["kpis"] and d["charts"] and d["event_columns"]
    assert d["trends"][d["main_metric"]]["status"] == "ok"
    assert d["insights"][0]["level"] == "headline"
    assert d["meta"]["quality"]["outliers_removed"] >= 2             # 99999 and -5 removed
    assert c.get(f"/api/analysis?{Q}&hazard={hz}").json()["meta"]["from_cache"] is True and prov.calls == 1
    assert c.get(f"/api/export/csv?{Q}&hazard={hz}").text.startswith("year,")
    assert c.get(f"/api/export/csv?{Q}&hazard={hz}&kind=events").status_code == 200
    assert c.get(f"/api/export/pdf?{Q}&hazard={hz}").content[:4] == b"%PDF"


def test_hazards_do_not_share_cache_and_precip_hazards_share_raw_data():
    c, prov = make()
    c.get(f"/api/analysis?{Q}")                                      # heatwave: fetch #1 (tmax)
    c.get(f"/api/analysis?{Q}&hazard=drought")                       # fetch #2 (precip)
    c.get(f"/api/analysis?{Q}&hazard=heavy_rainfall")                # reuses precip raw data
    assert prov.calls == 2
    assert c.get("/api/hazards").json()["hazards"][1]["id"] == "heavy_rainfall"


def test_percentile_normalised_for_drought_so_cache_not_fragmented():
    c, prov = make()
    c.get(f"/api/analysis?{Q}&hazard=drought&percentile=90")
    assert c.get(f"/api/analysis?{Q}&hazard=drought&percentile=99").json()["meta"]["from_cache"] is True
