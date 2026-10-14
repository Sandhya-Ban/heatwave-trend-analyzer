from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ProviderError
from app.main import create_app
from app.store import Store
from app.synthetic import SyntheticProvider


class CountingProvider(SyntheticProvider):
    def __init__(self):
        self.calls = 0
        self.fail = None

    def fetch_tmax(self, lat, lon, start, end):
        self.calls += 1
        if self.fail:
            raise self.fail
        return super().fetch_tmax(lat, lon, start, end)

    def fetch_precip(self, lat, lon, start, end):
        self.calls += 1
        if self.fail:
            raise self.fail
        return super().fetch_precip(lat, lon, start, end)


def make(**over):
    cfg = Settings(**{"rate_limit_general": 1000, "rate_limit_heavy": 1000, **over})
    prov = CountingProvider()
    app = create_app(cfg, prov, Store("", "t_" + str(id(prov)), 30), today=lambda: date(2026, 10, 12))
    return TestClient(app, raise_server_exceptions=False), prov


Q = "lat=17.38&lon=78.48&start_year=1991&end_year=2020"


def test_health_and_hazards():
    c, _ = make()
    assert c.get("/api/health").json()["status"] == "ok"
    assert c.get("/api/hazards").json()["hazards"][0]["id"] == "heatwave"


def test_analysis_shape_and_cache_hit():
    c, prov = make()
    r = c.get(f"/api/analysis?{Q}")
    assert r.status_code == 200
    d = r.json()
    assert d["meta"]["from_cache"] is False and len(d["yearly"]) == 30
    assert d["meta"]["quality"]["outliers_removed"] >= 1          # synthetic 999 value removed
    assert d["trends"]["heatwave_days"]["status"] == "ok"
    assert any(i["level"] == "headline" for i in d["insights"])
    r2 = c.get(f"/api/analysis?{Q}").json()
    assert r2["meta"]["from_cache"] is True and prov.calls == 1
    # different definition params reuse the cached raw data (no second fetch) but recompute
    r3 = c.get(f"/api/analysis?{Q}&percentile=90&min_days=4").json()
    assert r3["meta"]["from_cache"] is False and prov.calls == 1 and r3["params"]["percentile"] == 90


def test_bbox_uses_centroid():
    c, _ = make()
    d = c.get("/api/analysis?min_lat=16&max_lat=18&min_lon=77&max_lon=79&start_year=1991&end_year=2020").json()
    assert d["region"]["lat"] == 17.0 and d["region"]["lon"] == 78.0 and d["region"]["bbox"] == [16, 18, 77, 79]


@pytest.mark.parametrize("qs,code", [
    ("lat=91&lon=0&start_year=1991&end_year=2020", 422),
    ("lat=0&lon=181&start_year=1991&end_year=2020", 422),
    ("lat=abc&lon=0", 422), ("lat=nan&lon=0", 422), ("lat=inf&lon=0", 422),
    ("start_year=1991&end_year=2020", 422),                                   # no region
    ("lat=1&lon=1&min_lat=0&max_lat=1&min_lon=0&max_lon=1", 422),              # point and box
    ("min_lat=0&max_lat=1&min_lon=0", 422),                                    # partial box
    ("min_lat=5&max_lat=1&min_lon=0&max_lon=1", 422),                          # inverted
    ("min_lat=0&max_lat=30&min_lon=0&max_lon=1", 422),                         # too large
    ("lat=1&lon=1&start_year=2000&end_year=2005", 422),                        # <10 years
    ("lat=1&lon=1&start_year=2010&end_year=2000", 422),
    ("lat=1&lon=1&start_year=1900&end_year=2000", 422),
    ("lat=1&lon=1&start_year=2000&end_year=2027", 422),                        # future
    ("lat=1&lon=1&hazard=flood", 400),
    ("lat=1&lon=1&percentile=50", 422), ("lat=1&lon=1&min_days=1", 422),
    ("lat=1&lon=1&hazard=" + "x" * 500, 422),
])
def test_validation_rejects_bad_input(qs, code):
    c, prov = make()
    r = c.get(f"/api/analysis?{qs}")
    assert r.status_code == code and prov.calls == 0 and "Traceback" not in r.text


def test_injection_strings_are_inert():
    c, prov = make()
    assert c.get("/api/analysis?lat=1;DROP TABLE&lon=2").status_code == 422
    assert c.get("/api/analysis?lat=1&lon=2&hazard=%24where").status_code == 400
    assert prov.calls == 0


def test_current_year_partial_is_excluded_from_trend():
    c, _ = make()
    d = c.get("/api/analysis?lat=17&lon=78&start_year=2000&end_year=2026").json()
    last = d["yearly"][-1]
    assert last["year"] == 2026 and last["reliable"] is False
    assert d["trends"]["heatwave_days"]["n"] == 26
    assert any("excluded" in i["text"] for i in d["insights"])


def test_provider_failure_is_502_and_not_cached():
    c, prov = make()
    prov.fail = ProviderError("upstream down")
    r = c.get(f"/api/analysis?{Q}")
    assert r.status_code == 502 and "upstream down" in r.json()["detail"]
    prov.fail = None
    assert c.get(f"/api/analysis?{Q}").status_code == 200


def test_unexpected_error_is_generic_500():
    c, prov = make()
    prov.fail = RuntimeError("secret db password")
    r = c.get(f"/api/analysis?{Q}")
    assert r.status_code == 500 and "secret" not in r.text


def test_rate_limit_heavy_then_429_with_retry_after():
    c, _ = make(rate_limit_heavy=3)
    codes = [c.get(f"/api/analysis?{Q}").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert "Retry-After" in c.get(f"/api/analysis?{Q}").headers
    assert c.get("/api/health").status_code == 200       # light bucket unaffected


def test_exports():
    c, _ = make()
    r = c.get(f"/api/export/csv?{Q}")
    assert r.status_code == 200 and r.text.splitlines()[0].startswith("year,events") and len(r.text.splitlines()) == 31
    assert "attachment" in r.headers["content-disposition"]
    assert c.get(f"/api/export/csv?{Q}&kind=events").text.startswith("start,end")
    assert c.get(f"/api/export/csv?{Q}&kind=../etc").status_code == 422
    pdf = c.get(f"/api/export/pdf?{Q}")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_geocode_validation_and_results():
    c, _ = make()
    assert c.get("/api/geocode?q=a").status_code == 422
    assert c.get("/api/geocode?q=" + "a" * 200).status_code == 422
    assert c.get("/api/geocode?q=%3Cscript%3E").status_code in (200, 422)
    assert c.get("/api/geocode?q=hyder").json()["results"][0]["name"] == "Hyderabad"


def test_security_headers_present():
    c, _ = make()
    h = c.get("/api/health").headers
    assert h["x-content-type-options"] == "nosniff" and "default-src" in h["content-security-policy"]


def test_cors_origin_trailing_slash_normalized(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://heatwave-analyzer.netlify.app/")
    s = Settings.from_env()
    assert s.cors_origins == ("https://heatwave-analyzer.netlify.app",)

