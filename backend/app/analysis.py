"""Pure computation: cleaned series -> JSON-safe analysis document (no I/O). Supports 3 hazards."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from . import hazards, rainfall
from .errors import DataQualityError
from .insights import build_insights
from .stats import analyze_trend

MAX_EVENTS_RETURNED = 600
HAZARD_VARIABLE = {"heatwave": "tmax", "heavy_rainfall": "precip", "drought": "precip"}

SPECS = {
    "heatwave": {
        "label": "Heatwave", "main_key": "heatwave_days", "noun": "heatwave days", "per_year_unit": "heatwave days/yr",
        "trend_metrics": ("heatwave_days", "events", "max_duration", "mean_tmax_c"),
        "secondary": [("events", "Heatwave frequency", "events"), ("max_duration", "Longest event each year", "days"),
                      ("mean_tmax_c", "Context: mean annual maximum temperature", "°C")],
        "none_text": "No heatwaves met the definition in this period.",
        "stripe": {"field": "heatwave_days", "label": "heatwave days"},
        "charts": [
            {"title": "Heatwaves per year", "field": "events", "rolling": "events_rolling5", "trend": "events", "unit": "events"},
            {"title": "Heatwave days per year", "field": "heatwave_days", "rolling": "heatwave_days_rolling5", "trend": "heatwave_days", "unit": "days"},
            {"title": "Longest heatwave each year", "field": "max_duration", "trend": "max_duration", "unit": "days"},
            {"title": "Average daily high temperature", "field": "mean_tmax_c", "trend": "mean_tmax_c", "unit": "°C", "kind": "line", "digits": 1}],
        "event_columns": [{"key": "start", "label": "Start"}, {"key": "end", "label": "End"},
                          {"key": "duration_days", "label": "Days", "digits": 0},
                          {"key": "peak_tmax_c", "label": "Peak °C", "digits": 1},
                          {"key": "mean_excess_c", "label": "Avg above threshold °C", "digits": 1}],
        "event_sort": "duration_days", "events_title": "Longest heatwaves",
        "yearly_columns": ["year", "events", "heatwave_days", "max_duration", "mean_duration", "mean_intensity_c",
                           "max_intensity_c", "mean_tmax_c", "coverage", "reliable", "events_rolling5", "heatwave_days_rolling5"],
    },
    "heavy_rainfall": {
        "label": "Heavy rainfall", "main_key": "events", "noun": "heavy-rainfall days", "per_year_unit": "heavy-rain days/yr",
        "trend_metrics": ("events", "rx1day_mm", "heavy_total_mm", "annual_total_mm"),
        "secondary": [("rx1day_mm", "Wettest single day each year", "mm"), ("heavy_total_mm", "Rain falling on heavy days", "mm"),
                      ("annual_total_mm", "Context: total annual rainfall", "mm")],
        "none_text": "No days exceeded the heavy-rainfall threshold in this period.",
        "stripe": {"field": "events", "label": "heavy-rain days"},
        "charts": [
            {"title": "Heavy-rainfall days per year", "field": "events", "rolling": "events_rolling5", "trend": "events", "unit": "days"},
            {"title": "Wettest day of each year", "field": "rx1day_mm", "trend": "rx1day_mm", "unit": "mm", "digits": 1},
            {"title": "Rain falling on heavy days", "field": "heavy_total_mm", "rolling": "heavy_total_mm_rolling5", "trend": "heavy_total_mm", "unit": "mm", "digits": 1},
            {"title": "Total annual rainfall", "field": "annual_total_mm", "trend": "annual_total_mm", "unit": "mm", "kind": "line", "digits": 0}],
        "event_columns": [{"key": "start", "label": "Date"}, {"key": "precip_mm", "label": "Rain mm", "digits": 1},
                          {"key": "excess_mm", "label": "Above threshold mm", "digits": 1}],
        "event_sort": "precip_mm", "events_title": "Heaviest rainfall days",
        "yearly_columns": ["year", "events", "rx1day_mm", "heavy_total_mm", "annual_total_mm", "coverage", "reliable",
                           "events_rolling5", "heavy_total_mm_rolling5"],
    },
    "drought": {
        "label": "Drought", "main_key": "drought_months", "noun": "drought months", "per_year_unit": "drought months/yr",
        "trend_metrics": ("drought_months", "events", "max_duration", "annual_total_mm"),
        "secondary": [("events", "Drought events started", "events"), ("max_duration", "Longest drought each year", "months"),
                      ("annual_total_mm", "Context: total annual rainfall", "mm")],
        "none_text": "No drought events (2+ consecutive months with SPI-3 at or below -1) occurred in this period.",
        "stripe": {"field": "drought_months", "label": "drought months"},
        "charts": [
            {"title": "Drought months per year", "field": "drought_months", "rolling": "drought_months_rolling5", "trend": "drought_months", "unit": "months"},
            {"title": "Drought events started", "field": "events", "rolling": "events_rolling5", "trend": "events", "unit": "events"},
            {"title": "Longest drought each year", "field": "max_duration", "trend": "max_duration", "unit": "months"},
            {"title": "Total annual rainfall", "field": "annual_total_mm", "trend": "annual_total_mm", "unit": "mm", "kind": "line", "digits": 0}],
        "event_columns": [{"key": "start", "label": "Start"}, {"key": "end", "label": "End"},
                          {"key": "duration_months", "label": "Months", "digits": 0},
                          {"key": "min_spi", "label": "Lowest SPI-3", "digits": 2}],
        "event_sort": "duration_months", "events_title": "Longest droughts",
        "yearly_columns": ["year", "events", "drought_months", "max_duration", "min_spi", "annual_total_mm", "coverage",
                           "reliable", "events_rolling5", "drought_months_rolling5"],
    },
}


def json_safe(o):
    """Recursively replace NaN/inf with None and numpy scalars with Python scalars."""
    if isinstance(o, dict):
        return {str(k): json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [json_safe(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _heatwave(series, start_year, end_year, percentile, min_days):
    p = hazards.HeatwaveParams(percentile=percentile, min_days=min_days)
    thr = hazards.compute_thresholds(series, p)
    if np.isnan(thr).all():
        raise DataQualityError("not enough data to establish a temperature threshold")
    events = hazards.detect_heatwaves(series, thr, p)
    yearly = hazards.yearly_metrics(series, events, start_year, end_year)
    hazards.add_rolling(yearly)
    f = thr[~np.isnan(thr)]
    summary = {"min_c": round(float(f.min()), 1), "max_c": round(float(f.max()), 1), "mean_c": round(float(f.mean()), 1),
               "days_with_threshold": int(f.size)}
    defn = (f"A heatwave is {min_days}+ consecutive days with maximum temperature above the {percentile:g}th percentile "
            "for that calendar day (+/-7-day window), computed from this same period.")
    caveat = (defn + " By construction roughly 5% of days exceed it, so the analysis shows changes in how heat is "
              "distributed over time, not absolute severity. ERA5 is a ~25 km reanalysis grid: it can differ from a "
              "station's readings, and results are for one grid cell (for a bounding box, its centre).")
    totals = {"events": len(events), "heatwave_days": int(sum(e["duration_days"] for e in events)),
              "longest_event_days": max((e["duration_days"] for e in events), default=0)}
    kpis = [{"value": totals["events"], "label": "heatwaves"}, {"value": totals["heatwave_days"], "label": "heatwave days"},
            {"value": totals["longest_event_days"], "label": "days in the longest"},
            {"value": f"{summary['mean_c']}°C", "label": "average threshold"}]
    ext = None
    if events:
        lg = max(events, key=lambda e: (e["duration_days"], e["peak_tmax_c"]))
        ext = f"Longest heatwave: {lg['duration_days']} days starting {lg['start']} (peak {lg['peak_tmax_c']} C)."
    return events, yearly, summary, totals, kpis, defn, caveat, ext


def _heavy(series, start_year, end_year, percentile):
    events, yearly, summary = rainfall.heavy_rain(series, percentile, start_year, end_year)
    hazards.add_rolling(yearly, keys=("events", "heavy_total_mm"))
    defn = (f"A heavy-rainfall day has more than the {percentile:g}th percentile of wet-day rainfall "
            f"(wet day = at least {rainfall.WET_MM:g} mm), here {summary['threshold_mm']} mm.")
    caveat = (defn + " The threshold comes from this same period, so about " f"{100 - percentile:g}% of wet days exceed it by "
              "construction. Reanalysis rainfall is smoother than gauge data and tends to underestimate extremes, "
              "so use it for trends rather than absolute amounts.")
    totals = {"events": len(events), "heavy_days": len(events)}
    mx = max(events, key=lambda e: e["precip_mm"]) if events else None
    kpis = [{"value": len(events), "label": "heavy-rain days"}, {"value": f"{summary['threshold_mm']} mm", "label": "heavy-day threshold"},
            {"value": f"{mx['precip_mm']} mm" if mx else "-", "label": "wettest day"},
            {"value": summary["wet_days"], "label": "wet days analysed"}]
    ext = f"Heaviest day: {mx['precip_mm']} mm on {mx['start']}." if mx else None
    return events, yearly, summary, totals, kpis, defn, caveat, ext


def _drought(series, start_year, end_year):
    events, yearly, summary = rainfall.drought(series, start_year, end_year)
    hazards.add_rolling(yearly, keys=("events", "drought_months"))
    defn = ("A drought month has a 3-month Standardized Precipitation Index (SPI-3) at or below -1; a drought event is "
            f"{rainfall.MIN_DROUGHT_MONTHS}+ consecutive such months.")
    caveat = (defn + " SPI is relative to this same period's rainfall for each calendar month, so it measures dryness "
              "against local norms, not water supply; about 16% of months fall at or below -1 by construction. "
              "It ignores temperature and evaporation, and reanalysis rainfall can differ from gauges.")
    total_months = int(sum(r["drought_months"] for r in yearly))
    totals = {"events": len(events), "drought_months": total_months}
    lg = max(events, key=lambda e: (e["duration_months"], -e["min_spi"])) if events else None
    kpis = [{"value": len(events), "label": "droughts"}, {"value": total_months, "label": "drought months"},
            {"value": lg["duration_months"] if lg else 0, "label": "months in the longest"},
            {"value": min((e["min_spi"] for e in events), default="-"), "label": "lowest SPI-3"}]
    ext = (f"Longest drought: {lg['duration_months']} months starting {lg['start']} (lowest SPI-3 {lg['min_spi']})."
           if lg else None)
    return events, yearly, summary, totals, kpis, defn, caveat, ext


def run_analysis(series, quality: dict, *, start_year: int, end_year: int, percentile: float,
                 min_days: int, label: str, source: str, elevation, hazard: str = "heatwave") -> dict:
    spec = SPECS[hazard]
    if hazard == "heatwave":
        res = _heatwave(series, start_year, end_year, percentile, min_days)
    elif hazard == "heavy_rainfall":
        res = _heavy(series, start_year, end_year, percentile)
    else:
        res = _drought(series, start_year, end_year)
    events, yearly, thr_summary, totals, kpis, defn, caveat, ext = res

    rel = [r for r in yearly if r["reliable"]]
    trends = {}
    for m in spec["trend_metrics"]:
        pts = [(r["year"], r[m]) for r in rel if r.get(m) is not None]
        trends[m] = analyze_trend([a for a, _ in pts], [b for _, b in pts])
    totals.update({"reliable_years": len(rel), "years_requested": len(yearly)})

    spec_i = {**spec, "caveat": caveat}
    doc = {
        "hazard": hazard, "hazard_label": spec["label"], "definition": defn,
        "main_metric": spec["main_key"], "main_label": spec["noun"],
        "params": {"start_year": start_year, "end_year": end_year, "percentile": percentile, "min_days": min_days,
                   "baseline": f"{start_year}-{end_year} (full selected period)"},
        "meta": {"source": source, "elevation_m": elevation, "quality": quality,
                 "algorithm_version": hazards.ALGO_VERSION,
                 "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        "thresholds": thr_summary, "totals": totals, "kpis": kpis,
        "stripe": spec["stripe"], "charts": spec["charts"], "event_columns": spec["event_columns"],
        "event_sort": spec["event_sort"], "events_title": spec["events_title"],
        "yearly_columns": spec["yearly_columns"],
        "yearly": yearly, "events": events[-MAX_EVENTS_RETURNED:], "events_truncated": len(events) > MAX_EVENTS_RETURNED,
        "trends": trends,
    }
    doc["insights"] = build_insights(spec_i, trends, yearly, ext, quality, label)
    return json_safe(doc)
