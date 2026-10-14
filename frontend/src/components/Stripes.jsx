import { DEFAULT_THEME } from "../theme.js";

function color(v, max, ramp) {
  if (v === 0) return ramp[0];
  const i = Math.min(ramp.length - 1, 1 + Math.floor((v / Math.max(max, 1)) * (ramp.length - 1.001)));
  return ramp[i];
}

/**
 * One bar per year, shaded by the hazard's metric. Hatched = year excluded from trend
 * (too many gaps). The ramp follows the active hazard theme.
 */
export default function Stripes({ yearly, field = "heatwave_days", label = "heatwave days", theme = DEFAULT_THEME }) {
  const RAMP = theme.ramp;
  const val = (r) => r[field] || 0;
  const max = Math.max(...yearly.map(val), 1);
  return (
    <figure className="stripes-wrap">
      <div className="stripes" role="img" aria-label={`${label} per year, shaded from pale (none) to dark (most)`}>
        {yearly.map((r) => (
          <div key={r.year} className={r.reliable ? "stripe" : "stripe stripe-excluded"}
               style={r.reliable ? { background: color(val(r), max, RAMP) } : undefined}
               title={`${r.year}: ${val(r)} ${label}, ${r.events} event(s)${r.reliable ? "" : " (excluded: incomplete data)"}`} />
        ))}
      </div>
      <figcaption>
        <span>{yearly[0].year}</span>
        <span className="legend">
          fewer
          {RAMP.map((c) => <i key={c} style={{ background: c }} />)}
          more {label}
        </span>
        <span>{yearly[yearly.length - 1].year}</span>
      </figcaption>
    </figure>
  );
}
