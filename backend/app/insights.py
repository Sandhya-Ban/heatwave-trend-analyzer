"""Plain-language, deliberately cautious insight text derived from trend statistics."""
from __future__ import annotations


def _fmt_pct(c: dict, unit: str) -> str:
    if c["pct_change"] is None:
        return f"from 0 to {c['late_mean']:.1f} {unit}"
    return f"{c['pct_change']:+.0f}%"


def build_insights(spec: dict, trends: dict, yearly: list, extreme_text: str | None, quality: dict, label: str) -> list:
    out: list = []
    key, noun, unit = spec["main_key"], spec["noun"], spec["per_year_unit"]
    t = trends.get(key, {})
    if t.get("status") != "ok":
        out.append({"level": "warning", "text":
                    f"Not enough reliable years ({t.get('n', 0)} of the {t.get('min_required', 10)} needed) "
                    "to estimate a trend. Choose a longer range or a location with fewer data gaps."})
    else:
        c, mk = t["comparison"], t["mann_kendall"]
        ea, la = c["early_years"], c["late_years"]
        win = (f"{ea[0]}-{ea[1]} averaged {c['early_mean']:.1f} {unit}, "
               f"{la[0]}-{la[1]} averaged {c['late_mean']:.1f}")
        if t["significant"]:
            verb = "increased" if t["direction"] == "increasing" else "decreased"
            out.append({"level": "headline", "text":
                        f"{noun[0].upper() + noun[1:]} have {verb} in {label} ({_fmt_pct(c, unit)}): {win}. "
                        f"The Mann-Kendall test finds this trend statistically significant "
                        f"(p = {mk['p_value']:.3f}; Sen's slope {mk['sen_slope_per_decade']:+.2f} per decade)."})
        else:
            out.append({"level": "headline", "text":
                        f"No statistically significant trend in {noun} for {label} "
                        f"(Mann-Kendall p = {mk['p_value']:.2f}). The early/late comparison shows {_fmt_pct(c, unit)} "
                        f"({win}), but that gap is within normal year-to-year variability."})
    for k, lab, u in spec.get("secondary", []):
        s = trends.get(k, {})
        if s.get("status") == "ok":
            out.append({"level": "info", "text":
                        f"{lab}: {s['ols']['slope_per_decade']:+.2f} {u} per decade (linear fit, p = {s['ols']['p_value']:.2f}; "
                        f"Mann-Kendall p = {s['mann_kendall']['p_value']:.2f})."})
    out.append({"level": "info", "text": extreme_text or spec["none_text"]})
    excluded = [r["year"] for r in yearly if not r["reliable"]]
    if excluded:
        shown = ", ".join(map(str, excluded[:6])) + ("..." if len(excluded) > 6 else "")
        out.append({"level": "warning", "text":
                    f"{len(excluded)} year(s) were excluded from trend statistics because under 90% of days had valid "
                    f"data ({shown})."})
    if quality["outliers_removed"] or quality["missing_days"]:
        out.append({"level": "info", "text":
                    f"Data cleaning: {quality['missing_days']} missing day(s) treated as gaps and "
                    f"{quality['outliers_removed']} physically implausible value(s) removed."})
    out.append({"level": "caveat", "text": spec["caveat"]})
    return out
