"""Open-Meteo access (ERA5 reanalysis archive + geocoding).

Safe-access rules:
  * only fixed hostnames are ever contacted; user input is passed as query *parameters*
    (never concatenated into a URL), so there is no SSRF surface;
  * timeouts, bounded retries with exponential backoff on 429/5xx/network errors;
  * response shape is validated before anything downstream sees it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

import httpx

from .errors import ProviderError

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
SOURCE_NAME = "Open-Meteo Historical Weather API (ERA5 reanalysis)"


@dataclass
class RawSeries:
    dates: list            # ISO date strings
    tmax: list             # floats / None, same length as dates
    units: str             # as reported by the provider, e.g. "°C"
    elevation: Optional[float]
    source: str = SOURCE_NAME


class OpenMeteoProvider:
    def __init__(self, timeout: float = 60.0, retries: int = 3,
                 client: Optional[httpx.Client] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self._client = client or httpx.Client(timeout=timeout, headers={"User-Agent": "climate-hazard-analyzer/1.0"})
        self._retries = max(1, retries)
        self._sleep = sleep

    def _get_json(self, url: str, params: dict) -> dict:
        last = "unknown error"
        for attempt in range(self._retries):
            try:
                r = self._client.get(url, params=params)
            except httpx.HTTPError as exc:          # timeouts, DNS, connection resets
                last = f"network error ({type(exc).__name__})"
            else:
                if r.status_code == 200:
                    try:
                        data = r.json()
                    except ValueError:
                        raise ProviderError("provider returned invalid JSON")
                    if not isinstance(data, dict):
                        raise ProviderError("provider returned unexpected payload")
                    if data.get("error"):
                        raise ProviderError(f"provider rejected request: {str(data.get('reason', ''))[:200]}")
                    return data
                if r.status_code == 429 or r.status_code >= 500:
                    last = f"HTTP {r.status_code}"
                else:                               # 4xx: retrying will not help
                    reason = ""
                    try:
                        reason = str(r.json().get("reason", ""))[:200]
                    except Exception:
                        pass
                    raise ProviderError(f"provider rejected request (HTTP {r.status_code}) {reason}".strip())
            if attempt < self._retries - 1:
                self._sleep(0.5 * (2 ** attempt))
        raise ProviderError(f"provider unavailable after {self._retries} attempts: {last}")

    def _fetch_var(self, lat, lon, start, end, var: str, default_units: str) -> RawSeries:
        params = {"latitude": lat, "longitude": lon, "start_date": start.isoformat(), "end_date": end.isoformat(),
                  "daily": var, "models": "era5", "timezone": "GMT"}
        if var == "temperature_2m_max":
            params["temperature_unit"] = "celsius"
        else:
            params["precipitation_unit"] = "mm"
        data = self._get_json(ARCHIVE_URL, params)
        daily = data.get("daily")
        if not isinstance(daily, dict):
            raise ProviderError("provider response missing 'daily' block")
        times, vals = daily.get("time"), daily.get(var)
        if not isinstance(times, list) or not isinstance(vals, list) or len(times) != len(vals):
            raise ProviderError("provider response has inconsistent time/value arrays")
        if not times:
            raise ProviderError("provider returned no data for this location/range")
        units = (data.get("daily_units") or {}).get(var, default_units)
        elev = data.get("elevation")
        return RawSeries(times, vals, str(units), float(elev) if isinstance(elev, (int, float)) else None)

    def fetch_tmax(self, lat: float, lon: float, start: date, end: date) -> RawSeries:
        return self._fetch_var(lat, lon, start, end, "temperature_2m_max", "°C")

    def fetch_precip(self, lat: float, lon: float, start: date, end: date) -> RawSeries:
        return self._fetch_var(lat, lon, start, end, "precipitation_sum", "mm")

    def fetch_daily(self, lat, lon, start, end, variable: str = "tmax") -> RawSeries:
        if variable == "tmax":
            return self.fetch_tmax(lat, lon, start, end)
        if variable == "precip":
            return self.fetch_precip(lat, lon, start, end)
        raise ProviderError(f"unsupported variable '{variable}'")

    def geocode(self, query: str, count: int = 8) -> list:
        data = self._get_json(GEOCODE_URL, {"name": query, "count": count, "language": "en", "format": "json"})
        out = []
        for r in data.get("results") or []:
            try:
                out.append({
                    "name": str(r["name"]),
                    "admin1": r.get("admin1"),
                    "country": r.get("country"),
                    "lat": float(r["latitude"]), "lon": float(r["longitude"]),
                })
            except (KeyError, TypeError, ValueError):
                continue
        return out
