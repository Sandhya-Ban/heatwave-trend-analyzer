import httpx
import pytest

from app.errors import ProviderError
from app.provider import OpenMeteoProvider
from datetime import date


def prov(handler, retries=3):
    sleeps = []
    p = OpenMeteoProvider(client=httpx.Client(transport=httpx.MockTransport(handler)), retries=retries, sleep=sleeps.append)
    p.sleeps = sleeps
    return p


OK = {"elevation": 540.0, "daily_units": {"temperature_2m_max": "°C"},
      "daily": {"time": ["2020-01-01", "2020-01-02"], "temperature_2m_max": [30.1, None]}}


def test_success_and_params():
    seen = {}
    def h(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json=OK)
    s = prov(h).fetch_tmax(17.0, 78.0, date(2020, 1, 1), date(2020, 1, 2))
    assert s.tmax == [30.1, None] and s.elevation == 540.0
    assert seen["daily"] == "temperature_2m_max" and seen["models"] == "era5" and seen["start_date"] == "2020-01-01"


def test_retries_on_429_then_succeeds_with_backoff():
    n = {"c": 0}
    def h(req):
        n["c"] += 1
        return httpx.Response(429) if n["c"] < 3 else httpx.Response(200, json=OK)
    p = prov(h)
    assert p.fetch_tmax(1, 1, date(2020, 1, 1), date(2020, 1, 2)).dates
    assert n["c"] == 3 and p.sleeps == [0.5, 1.0]


def test_gives_up_after_retries_and_on_timeouts():
    p = prov(lambda r: httpx.Response(503))
    with pytest.raises(ProviderError, match="after 3 attempts"):
        p.fetch_tmax(1, 1, date(2020, 1, 1), date(2020, 1, 2))
    def boom(req): raise httpx.ConnectTimeout("t")
    with pytest.raises(ProviderError, match="network"):
        prov(boom).fetch_tmax(1, 1, date(2020, 1, 1), date(2020, 1, 2))


def test_4xx_not_retried_and_malformed_payloads_rejected():
    n = {"c": 0}
    def h(req):
        n["c"] += 1
        return httpx.Response(400, json={"error": True, "reason": "bad date"})
    with pytest.raises(ProviderError, match="bad date"):
        prov(h).fetch_tmax(1, 1, date(2020, 1, 1), date(2020, 1, 2))
    assert n["c"] == 1
    for payload in ({"daily": {"time": ["2020-01-01"], "temperature_2m_max": []}}, {"nodaily": 1},
                    {"daily": {"time": [], "temperature_2m_max": []}}, [1, 2]):
        with pytest.raises(ProviderError):
            prov(lambda r, p=payload: httpx.Response(200, json=p)).fetch_tmax(1, 1, date(2020, 1, 1), date(2020, 1, 2))
    with pytest.raises(ProviderError, match="invalid JSON"):
        prov(lambda r: httpx.Response(200, text="<html>")).fetch_tmax(1, 1, date(2020, 1, 1), date(2020, 1, 2))


def test_geocode_skips_malformed_rows():
    body = {"results": [{"name": "Hyderabad", "latitude": 17.4, "longitude": 78.5, "country": "India", "admin1": "Telangana"},
                        {"name": "broken"}]}
    assert [r["name"] for r in prov(lambda r: httpx.Response(200, json=body)).geocode("hyd")] == ["Hyderabad"]
    assert prov(lambda r: httpx.Response(200, json={})).geocode("zzz") == []
