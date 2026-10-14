"""Offline demo provider. Produces *generated* data (seasonal cycle + warming drift + AR(1) noise,
with deliberate gaps and a bad value) so the app can be exercised without internet.
Always labelled as synthetic in API metadata; never use it for real conclusions."""
from __future__ import annotations

import zlib
from datetime import date, timedelta

import numpy as np

from .provider import RawSeries

SOURCE_NAME = "SYNTHETIC DEMO DATA (not real observations)"


class SyntheticProvider:
    def fetch_tmax(self, lat: float, lon: float, start: date, end: date) -> RawSeries:
        n = (end - start).days + 1
        rng = np.random.default_rng(zlib.crc32(f"{lat:.2f},{lon:.2f}".encode()))
        days = [start + timedelta(days=i) for i in range(n)]
        doy = np.array([d.timetuple().tm_yday for d in days])
        yrs = np.array([d.year for d in days]) - 1990
        base = 27 - 0.25 * abs(lat) * 0.4
        season = 9 * np.sin(2 * np.pi * (doy - 105) / 365.25) * (1 if lat >= 0 else -1)
        noise = np.zeros(n)
        e = rng.normal(0, 1.8, n)
        for i in range(1, n):
            noise[i] = 0.7 * noise[i - 1] + e[i]
        t = np.round(base + season + 0.035 * yrs + noise, 1).astype(object)
        for i in rng.choice(n, size=max(1, n // 300), replace=False):
            t[i] = None
        if n > 50:
            t[int(rng.integers(5, n - 5))] = 999.0   # sensor-style garbage value
        return RawSeries([d.isoformat() for d in days], t.tolist(), "°C", 100.0, SOURCE_NAME)

    def fetch_precip(self, lat: float, lon: float, start: date, end: date) -> RawSeries:
        n = (end - start).days + 1
        rng = np.random.default_rng(zlib.crc32(f"p{lat:.2f},{lon:.2f}".encode()))
        days = [start + timedelta(days=i) for i in range(n)]
        doy = np.array([d.timetuple().tm_yday for d in days])
        year = np.array([d.year for d in days])
        season = 0.5 + 0.4 * np.sin(2 * np.pi * (doy - 200) / 365.25)
        wet = rng.random(n) < np.clip(0.55 * season, 0.02, 0.9)
        yf = dict(zip(range(1900, 2101), rng.lognormal(0, 0.3, 201)))      # wet/dry years -> droughts
        factor = np.array([yf[y] for y in year]) * (1 + 0.004 * (year - 1990))
        amt = rng.gamma(0.7, 12.0, n) * factor
        p = np.round(np.where(wet, amt, 0.0), 1).astype(object)
        for i in rng.choice(n, size=max(1, n // 300), replace=False):
            p[i] = None
        if n > 50:
            p[int(rng.integers(5, n - 5))] = 99999.0      # garbage value
            p[int(rng.integers(5, n - 5))] = -5.0         # negative rainfall
        return RawSeries([d.isoformat() for d in days], p.tolist(), "mm", 100.0, SOURCE_NAME)

    def fetch_daily(self, lat, lon, start, end, variable: str = "tmax") -> RawSeries:
        return self.fetch_precip(lat, lon, start, end) if variable == "precip" else self.fetch_tmax(lat, lon, start, end)

    def geocode(self, query: str, count: int = 8) -> list:
        demo = [("Hyderabad", "Telangana", "India", 17.38, 78.48), ("Delhi", "Delhi", "India", 28.65, 77.21),
                ("Phoenix", "Arizona", "United States", 33.45, -112.07), ("Paris", "Île-de-France", "France", 48.85, 2.35)]
        q = query.lower()
        return [{"name": n, "admin1": a, "country": c, "lat": la, "lon": lo} for n, a, c, la, lo in demo if q in n.lower()][:count]
