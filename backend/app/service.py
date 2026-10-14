"""Orchestration: validate -> (DB cache | fetch+clean) -> analyse -> persist -> read back."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Optional

from . import hazards
from .analysis import HAZARD_VARIABLE, run_analysis
from .errors import DataQualityError, ProviderError
from .quality import clean_series
from .store import Store

ERA5_LATENCY_DAYS = 6   # most recent days are not yet available / still being finalised


@dataclass(frozen=True)
class AnalysisParams:
    lat: float
    lon: float
    start_year: int
    end_year: int
    percentile: float = 95.0
    min_days: int = 3
    bbox: Optional[tuple] = None   # (min_lat, max_lat, min_lon, max_lon) if the user drew a box
    hazard: str = "heatwave"

    @property
    def variable(self) -> str:
        return HAZARD_VARIABLE[self.hazard]

    @property
    def raw_key(self) -> str:
        return f"{self.variable}_{self.lat:.2f}_{self.lon:.2f}_{self.start_year}_{self.end_year}"

    @property
    def key(self) -> str:
        return f"{self.hazard}_{self.raw_key}_p{self.percentile:g}_m{self.min_days}"

    @property
    def label(self) -> str:
        if self.bbox:
            return f"the selected box (centre {self.lat:.2f}, {self.lon:.2f})"
        return f"{self.lat:.2f}, {self.lon:.2f}"


class AnalysisService:
    def __init__(self, store: Store, provider, *, cache_ttl_days: int = 30, fresh_ttl_hours: int = 24,
                 max_concurrent_fetches: int = 2, today: Callable[[], date] = date.today):
        self.store, self.provider, self.today = store, provider, today
        self.ttl = timedelta(days=cache_ttl_days)
        self.fresh_ttl = timedelta(hours=fresh_ttl_hours)
        self._sem = threading.BoundedSemaphore(max(1, max_concurrent_fetches))
        self._locks = [threading.Lock() for _ in range(64)]   # striped: one compute per key at a time

    def _max_age(self, p: AnalysisParams) -> timedelta:
        return self.fresh_ttl if p.end_year >= self.today().year else self.ttl

    def get_analysis(self, p: AnalysisParams) -> dict:
        age = self._max_age(p)
        with self._locks[hash(p.key) % len(self._locks)]:
            rec = self.store.get_analysis(p.key, age, hazards.ALGO_VERSION)
            from_cache = rec is not None
            if rec is None:
                self._compute_and_store(p, age)
                rec = self.store.get_analysis(p.key, age, hazards.ALGO_VERSION)   # read back from DB
                if rec is None:
                    raise ProviderError("analysis could not be read back from storage")
        doc = rec["analysis"]
        doc["region"] = {"lat": p.lat, "lon": p.lon, "bbox": list(p.bbox) if p.bbox else None,
                         "note": "Data are for one ERA5 grid cell (~25 km) at this point"
                                 + (" (the centre of the selected box)." if p.bbox else ".")}
        doc["meta"]["from_cache"] = from_cache
        return doc

    def _compute_and_store(self, p: AnalysisParams, age: timedelta) -> None:
        raw = self.store.get_raw(p.raw_key, age)
        if raw is None:
            end = min(date(p.end_year, 12, 31), self.today() - timedelta(days=ERA5_LATENCY_DAYS))
            start = date(p.start_year, 1, 1)
            if end < start:
                raise DataQualityError("requested range has no available data yet")
            with self._sem:
                series = self.provider.fetch_daily(p.lat, p.lon, start, end, p.variable)
            raw = {"dates": series.dates, "tmax": series.tmax, "units": series.units,
                   "elevation": series.elevation, "source": series.source}
            self.store.put_raw(p.raw_key, raw)
        s, q = clean_series(raw["dates"], raw["tmax"], raw.get("units", "°C" if p.variable == "tmax" else "mm"), kind=p.variable)
        doc = run_analysis(s, q.to_dict(), start_year=p.start_year, end_year=p.end_year,
                           percentile=p.percentile, min_days=p.min_days, label=p.label,
                           source=raw.get("source", ""), elevation=raw.get("elevation"), hazard=p.hazard)
        self.store.put_analysis(p.key, doc, hazards.ALGO_VERSION)
