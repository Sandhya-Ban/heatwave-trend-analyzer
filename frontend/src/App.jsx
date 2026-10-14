import { useCallback, useEffect, useRef, useState } from "react";
import MapPicker from "./components/MapPicker.jsx";
import Stripes from "./components/Stripes.jsx";
import YearChart from "./components/YearChart.jsx";
import Insights from "./components/Insights.jsx";
import EventsTable from "./components/EventsTable.jsx";
import { HAZARDS, THIS_YEAR, buildQuery, exportUrl, fetchAnalysis, searchPlaces } from "./api.js";
import { themeFor } from "./theme.js";

const DEFAULT_REGION = { mode: "point", lat: "28.61", lon: "77.21", label: "Delhi, India" };

export default function App() {
  const [region, setRegion] = useState({ ...DEFAULT_REGION, minLat: "", maxLat: "", minLon: "", maxLon: "" });
  const [period, setPeriod] = useState({ start: 1991, end: 2020 });
  const [definition, setDefinition] = useState({ percentile: 95, minDays: 3 });
  const [hazard, setHazard] = useState("heatwave");
  const [state, setState] = useState({ status: "idle", data: null, error: null, query: null });
  const [search, setSearch] = useState({ text: "", results: [], busy: false, error: null });
  const ctl = useRef(null);

  const run = useCallback(async () => {
    const { query, error } = buildQuery(region, period, definition, hazard);
    if (error) { setState((s) => ({ ...s, status: "error", error })); return; }
    ctl.current?.abort();
    ctl.current = new AbortController();
    const qs = query.toString();
    setState((s) => ({ ...s, status: "loading", error: null }));
    try {
      const data = await fetchAnalysis(qs, ctl.current.signal);
      setState({ status: "done", data, error: null, query: qs });
    } catch (e) {
      if (e.name !== "AbortError") setState((s) => ({ ...s, status: "error", error: e.message }));
    }
  }, [region, period, definition, hazard]);

  useEffect(() => { run(); /* initial load only */ // eslint-disable-line react-hooks/exhaustive-deps
    return () => ctl.current?.abort(); }, []);

  async function doSearch(e) {
    e.preventDefault();
    const text = search.text.trim();
    if (text.length < 2) { setSearch((s) => ({ ...s, error: "Type at least 2 characters." })); return; }
    setSearch((s) => ({ ...s, busy: true, error: null, results: [] }));
    try {
      const { results } = await searchPlaces(text);
      setSearch((s) => ({ ...s, busy: false, results, error: results.length ? null : "No places found. Try a nearby city name." }));
    } catch (err) { setSearch((s) => ({ ...s, busy: false, error: err.message })); }
  }

  // Selecting a place mirrors the label into the search box, so the chosen city
  // stays on screen instead of the input dropping back to its placeholder.
  const selectPoint = (lat, lon, label) => {
    setRegion((g) => ({ ...g, mode: "point", lat: String(+lat.toFixed(3)), lon: String(+lon.toFixed(3)), label }));
    setSearch((s) => ({ ...s, results: [], text: label }));
  };
  // Editing coordinates by hand invalidates the place name: drop it everywhere.
  const clearPlace = (patch) => {
    setRegion((g) => ({ ...g, ...patch, label: "" }));
    setSearch((s) => ({ ...s, results: [], text: "" }));
  };
  const pickPlace = (r) => selectPoint(r.lat, r.lon, [r.name, r.admin1, r.country].filter(Boolean).join(", "));
  const setMode = (mode) => setRegion((g) => ({ ...g, mode }));
  const theme = themeFor(hazard);          // one palette drives CSS, charts and tables
  const { status, data, error, query } = state;
  const headline = data?.insights.find((i) => i.level === "headline");

  return (
    <div className="app" data-theme={hazard}>
      <header className="top">
        <h1>Heatwave trend analyzer</h1>
        <p>How often, how long and how intense have heatwaves been where you are? Pick a place and a period.</p>
      </header>

      <div className="layout">
        <aside className="panel" aria-label="Analysis settings">
          <fieldset>
            <legend>Hazard</legend>
            <select aria-label="Hazard type" value={hazard} onChange={(e) => setHazard(e.target.value)}>
              {HAZARDS.map((h) => <option key={h.id} value={h.id}>{h.label}</option>)}
            </select>
          </fieldset>

          <fieldset>
            <legend>Region</legend>
            <div className="seg" role="group" aria-label="Region type">
              <button type="button" aria-pressed={region.mode === "point"} onClick={() => setMode("point")}>City or point</button>
              <button type="button" aria-pressed={region.mode === "box"} onClick={() => setMode("box")}>Lat-lon box</button>
            </div>
            <form className="search" onSubmit={doSearch}>
              <label className="sr" htmlFor="place">Search for a city or state</label>
              <input id="place" value={search.text} maxLength={80} placeholder="Search a city or state" onChange={(e) => setSearch((s) => ({ ...s, text: e.target.value }))} />
              <button type="submit" disabled={search.busy}>{search.busy ? "Searching" : "Search"}</button>
            </form>
            {search.error && <p className="field-error" role="alert">{search.error}</p>}
            {search.results.length > 0 && (
              <ul className="results">{search.results.map((r, i) => (
                <li key={i}><button type="button" onClick={() => pickPlace(r)}>{[r.name, r.admin1, r.country].filter(Boolean).join(", ")}</button></li>))}
              </ul>)}
            <MapPicker region={region} hazard={hazard}
              onPoint={(lat, lon) => selectPoint(lat, lon, `${+lat.toFixed(3)}, ${+lon.toFixed(3)}`)}
              onBox={(a, b, c, d) => setRegion((g) => ({ ...g, minLat: String(+a.toFixed(2)), maxLat: String(+b.toFixed(2)), minLon: String(+c.toFixed(2)), maxLon: String(+d.toFixed(2)) }))} />
            <p className="hint">{region.mode === "point" ? "Click the map to set a point." : "Click two opposite corners on the map, or type the edges. Data are taken at the box centre."}</p>
            {region.mode === "point" ? (
              <div className="grid2">
                <label>Latitude<input inputMode="decimal" value={region.lat} onChange={(e) => clearPlace({ lat: e.target.value })} /></label>
                <label>Longitude<input inputMode="decimal" value={region.lon} onChange={(e) => clearPlace({ lon: e.target.value })} /></label>
              </div>) : (
              <div className="grid2">
                {[["minLat", "South edge (min lat)"], ["maxLat", "North edge (max lat)"], ["minLon", "West edge (min lon)"], ["maxLon", "East edge (max lon)"]].map(([k, l]) => (
                  <label key={k}>{l}<input inputMode="decimal" value={region[k]} onChange={(e) => setRegion({ ...region, [k]: e.target.value })} /></label>))}
              </div>)}
          </fieldset>

          <fieldset>
            <legend>Time range</legend>
            <div className="grid2">
              <label>From<input type="number" min="1940" max={THIS_YEAR} value={period.start} onChange={(e) => setPeriod({ ...period, start: e.target.value })} /></label>
              <label>To<input type="number" min="1940" max={THIS_YEAR} value={period.end} onChange={(e) => setPeriod({ ...period, end: e.target.value })} /></label>
            </div>
          </fieldset>

          <details>
            <summary>{hazard === "drought" ? "Drought definition" : hazard === "heavy_rainfall" ? "Heavy-rainfall definition" : "Heatwave definition"}</summary>
            {hazard === "drought" ? (
              <p className="hint">A drought month has a 3-month Standardized Precipitation Index (SPI-3) at or below -1. A drought is 2 or more such months in a row. This definition is fixed.</p>
            ) : (
              <>
                <div className="grid2">
                  <label>Percentile<input type="number" min="80" max="99.5" step="0.5" value={definition.percentile} onChange={(e) => setDefinition({ ...definition, percentile: e.target.value })} /></label>
                  {hazard === "heatwave" && <label>Min. days in a row<input type="number" min="2" max="10" value={definition.minDays} onChange={(e) => setDefinition({ ...definition, minDays: e.target.value })} /></label>}
                </div>
                <p className="hint">{hazard === "heatwave"
                  ? "A heatwave is this many consecutive days above the percentile of daily maximum temperature for that time of year."
                  : "A heavy-rainfall day has more rain than this percentile of wet days (days with at least 1 mm)."}</p>
              </>
            )}
          </details>

          <button className="primary" onClick={run} disabled={status === "loading"}>{status === "loading" ? "Analyzing…" : `Analyze ${HAZARDS.find((h) => h.id === hazard).label.toLowerCase()}`}</button>
          {status === "error" && <p className="banner error" role="alert">{error}</p>}
        </aside>

        <main aria-live="polite">
          {status === "idle" && <p className="muted">Choose a region and run the analysis.</p>}
          {status === "loading" && !data && <p className="muted">Fetching the daily weather record and analyzing it. The first request for a place can take a few seconds.</p>}
          {data && (
            <div className={status === "loading" ? "results-area stale" : "results-area"}>
              {data.meta.source.startsWith("SYNTHETIC") && <p className="banner warn">Demo mode: these numbers are generated, not real observations.</p>}
              <section className="hero">
                <p className="place">{data.hazard_label} · {region.label || `${data.region.lat}, ${data.region.lon}`} · {data.params.start_year}–{data.params.end_year}</p>
                <h2>{headline ? headline.text : "Analysis complete"}</h2>
                <Stripes yearly={data.yearly} field={data.stripe.field} label={data.stripe.label} theme={theme} />
              </section>

              <div className="kpis">
                {data.kpis.map((k) => <div key={k.label}><b>{k.value}</b><span>{k.label}</span></div>)}
              </div>

              <div className="charts">
                {data.charts.map((c) => (
                  <YearChart key={c.title} title={c.title} yearly={data.yearly} field={c.field} rolling={c.rolling}
                    trend={data.trends[c.trend]} unit={c.unit} kind={c.kind} digits={c.digits ?? 0} theme={theme} />
                ))}
              </div>

              <h3 className="section">What the data says</h3>
              <Insights items={data.insights} />

              <h3 className="section">{data.events_title}</h3>
              <EventsTable events={data.events} columns={data.event_columns} sortKey={data.event_sort} />
              {data.events_truncated && <p className="hint">Showing the most recent {data.events.length} events.</p>}

              <div className="exports">
                <a href={exportUrl("yearly", query)} download>Download yearly CSV</a>
                <a href={exportUrl("events", query)} download>Download events CSV</a>
                <a href={exportUrl("pdf", query)} download>Download PDF report</a>
              </div>
              <p className="meta">Source: {data.meta.source}. {data.meta.from_cache ? "Served from the saved analysis." : "Freshly computed and saved."} Data quality: {Math.round(data.meta.quality.coverage * 100)}% of days usable.</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
