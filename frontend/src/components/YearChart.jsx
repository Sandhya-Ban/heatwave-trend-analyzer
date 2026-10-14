import { Chart as ChartJS, BarController, LineController, BarElement, LineElement, PointElement, CategoryScale, LinearScale, Tooltip, Legend } from "chart.js";
import { Chart } from "react-chartjs-2";

ChartJS.register(BarController, LineController, BarElement, LineElement, PointElement, CategoryScale, LinearScale, Tooltip, Legend);

import { DEFAULT_THEME, chartPalette } from "../theme.js";

/**
 * Yearly bars + 5-yr rolling mean + OLS fit line (reliable years only).
 * kind: "bar" | "line". Years flagged unreliable are drawn grey and never feed the lines.
 * Colours come from the hazard theme so the whole page reads as one hazard.
 */
export default function YearChart({ title, yearly, field, rolling, trend, unit, kind = "bar", digits = 0, theme = DEFAULT_THEME }) {
  const C = chartPalette(theme);
  const labels = yearly.map((r) => r.year);
  const vals = yearly.map((r) => r[field]);
  const reliable = yearly.map((r) => r.reliable);
  const datasets = [];
  if (kind === "bar") {
    datasets.push({ type: "bar", label: unit, data: vals, backgroundColor: reliable.map((ok) => (ok ? C.bar : C.unreliable)), borderWidth: 0, order: 3 });
  } else {
    datasets.push({ type: "line", label: unit, data: vals.map((v, i) => (reliable[i] ? v : null)), borderColor: C.line, backgroundColor: C.line, pointRadius: 2, borderWidth: 1.5, spanGaps: true, order: 3 });
  }
  if (rolling) datasets.push({ type: "line", label: "5-year average", data: yearly.map((r) => r[rolling]), borderColor: C.rolling, borderWidth: 2, pointRadius: 0, tension: 0.3, spanGaps: true, order: 1 });
  if (trend && trend.status === "ok") {
    const rel = yearly.filter((r) => r.reliable);
    const f = rel[0].year, l = rel[rel.length - 1].year;
    datasets.push({ type: "line", label: "Linear trend", data: labels.map((y) => (y === f ? trend.ols.fit_first : y === l ? trend.ols.fit_last : null)), borderColor: C.trend, borderDash: [6, 4], borderWidth: 2, pointRadius: 0, spanGaps: true, order: 2 });
  }
  const options = {
    responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "bottom", labels: { boxWidth: 12, font: { family: "Inter" } } },
      tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y == null ? "n/a" : c.parsed.y.toFixed(digits === 0 && c.dataset.label !== unit ? 1 : digits)}`,
        afterBody: (items) => { const r = yearly[items[0].dataIndex]; return r.reliable ? "" : `Excluded from trend (${Math.round(r.coverage * 100)}% data coverage)`; } } },
    },
    scales: {
      x: { grid: { display: false }, ticks: { maxTicksLimit: 10, font: { family: "Inter" } } },
      y: { beginAtZero: kind === "bar", title: { display: true, text: unit }, ticks: { precision: digits === 0 ? 0 : undefined } },
    },
  };
  const trendNote = trend && trend.status === "ok"
    ? `${trend.mann_kendall.sen_slope_per_decade >= 0 ? "+" : ""}${trend.mann_kendall.sen_slope_per_decade.toFixed(2)} per decade · ${trend.significant ? "significant" : "not significant"} (p=${trend.mann_kendall.p_value.toFixed(3)})`
    : "Not enough reliable years for a trend";
  return (
    <section className="chart-card">
      <h3>{title}</h3>
      <p className="chart-note">{trendNote}</p>
      <div className="chart-box"><Chart type="bar" data={{ labels, datasets }} options={options} /></div>
    </section>
  );
}
