// Pure helpers + fetch wrappers. Validation here mirrors the backend so users get instant feedback;
// the backend remains the authority.
export const THIS_YEAR = new Date().getFullYear();

export function num(v) {
  if (v === "" || v === null || v === undefined) return NaN;
  return Number(v);
}

/** Returns {error} or {query: URLSearchParams}. region: {mode:'point'|'box', ...strings} */
export const HAZARDS = [
  { id: "heatwave", label: "Heatwave" },
  { id: "heavy_rainfall", label: "Heavy rainfall" },
  { id: "drought", label: "Drought" },
];

export function buildQuery(region, period, definition, hazard = "heatwave") {
  const q = new URLSearchParams();
  const inRange = (v, lo, hi) => Number.isFinite(v) && v >= lo && v <= hi;
  if (region.mode === "box") {
    const [a, b, c, d] = [num(region.minLat), num(region.maxLat), num(region.minLon), num(region.maxLon)];
    if (!inRange(a, -90, 90) || !inRange(b, -90, 90) || !inRange(c, -180, 180) || !inRange(d, -180, 180))
      return { error: "Enter all four box edges as valid latitudes (-90 to 90) and longitudes (-180 to 180)." };
    if (a >= b || c >= d) return { error: "Box minimums must be smaller than maximums." };
    if (b - a > 10 || d - c > 10) return { error: "Box can be at most 10 degrees on each side." };
    q.set("min_lat", a); q.set("max_lat", b); q.set("min_lon", c); q.set("max_lon", d);
  } else {
    const lat = num(region.lat), lon = num(region.lon);
    if (!inRange(lat, -90, 90) || !inRange(lon, -180, 180))
      return { error: "Pick a place on the map or enter a valid latitude (-90 to 90) and longitude (-180 to 180)." };
    q.set("lat", lat); q.set("lon", lon);
  }
  const s = Math.trunc(num(period.start)), e = Math.trunc(num(period.end));
  if (!Number.isFinite(s) || !Number.isFinite(e)) return { error: "Enter a start and end year." };
  if (s < 1940) return { error: "Data starts in 1940. Choose a later start year." };
  if (e > THIS_YEAR) return { error: `End year cannot be after ${THIS_YEAR}.` };
  if (e - s + 1 < 10) return { error: "Choose at least 10 years so a trend can be measured." };
  q.set("start_year", s); q.set("end_year", e);
  if (!HAZARDS.some((h) => h.id === hazard)) return { error: "Choose a hazard type." };
  q.set("hazard", hazard);
  if (hazard !== "drought") {
    const pc = num(definition.percentile);
    if (!Number.isFinite(pc) || pc < 80 || pc > 99.5) return { error: "Percentile must be between 80 and 99.5." };
    q.set("percentile", pc);
  }
  if (hazard === "heatwave") {
    const md = Math.trunc(num(definition.minDays));
    if (!Number.isFinite(md) || md < 2 || md > 10) return { error: "Minimum days in a row must be between 2 and 10." };
    q.set("min_days", md);
  }
  return { query: q };
}

async function getJson(url, signal) {
  let res;
  try { res = await fetch(url, { signal }); }
  catch (e) { if (e.name === "AbortError") throw e; throw new Error("Cannot reach the server. Check your connection and try again."); }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok) {
    if (res.status === 429) throw new Error("Too many requests. Wait a few seconds and try again.");
    const d = body && body.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return body;
}

export const fetchAnalysis = (query, signal) => getJson(`/api/analysis?${query}`, signal);
export const searchPlaces = (q, signal) => getJson(`/api/geocode?q=${encodeURIComponent(q)}`, signal);
export const exportUrl = (kind, query) => (kind === "pdf" ? `/api/export/pdf?${query}` : `/api/export/csv?kind=${kind}&${query}`);
