import { describe, expect, it, vi, afterEach } from "vitest";
import { buildQuery, buildApiUrl, apiUrl, exportUrl, fetchAnalysis, searchPlaces, fetchHealth, fetchHazards } from "./api.js";

const def = { percentile: 95, minDays: 3 };
const pt = { mode: "point", lat: "28.6", lon: "77.2" };

describe("buildQuery", () => {
  it("builds a valid point query", () => {
    const r = buildQuery(pt, { start: 1991, end: 2020 }, def);
    expect(r.error).toBeUndefined();
    expect(r.query.get("lat")).toBe("28.6");
    expect(r.query.get("hazard")).toBe("heatwave");
  });
  it("rejects out-of-range and empty coordinates", () => {
    expect(buildQuery({ ...pt, lat: "95" }, { start: 1991, end: 2020 }, def).error).toBeTruthy();
    expect(buildQuery({ ...pt, lon: "" }, { start: 1991, end: 2020 }, def).error).toBeTruthy();
    expect(buildQuery({ ...pt, lat: "abc" }, { start: 1991, end: 2020 }, def).error).toBeTruthy();
  });
  it("rejects short, reversed, pre-1940 and future ranges", () => {
    expect(buildQuery(pt, { start: 2000, end: 2005 }, def).error).toMatch(/10 years/);
    expect(buildQuery(pt, { start: 2020, end: 1990 }, def).error).toBeTruthy();
    expect(buildQuery(pt, { start: 1930, end: 2000 }, def).error).toMatch(/1940/);
    expect(buildQuery(pt, { start: 2000, end: 2999 }, def).error).toMatch(/cannot be after/);
    expect(buildQuery(pt, { start: "", end: 2020 }, def).error).toBeTruthy();
  });
  it("validates boxes", () => {
    const box = { mode: "box", minLat: "10", maxLat: "12", minLon: "70", maxLon: "75" };
    expect(buildQuery(box, { start: 1991, end: 2020 }, def).query.get("min_lat")).toBe("10");
    expect(buildQuery({ ...box, maxLat: "5" }, { start: 1991, end: 2020 }, def).error).toMatch(/smaller/);
    expect(buildQuery({ ...box, maxLat: "40" }, { start: 1991, end: 2020 }, def).error).toMatch(/10 degrees/);
    expect(buildQuery({ ...box, minLon: "" }, { start: 1991, end: 2020 }, def).error).toBeTruthy();
  });
  it("sends only the parameters each hazard uses", () => {
    const hw = buildQuery(pt, { start: 1991, end: 2020 }, def, "heatwave").query;
    expect(hw.get("percentile")).toBe("95"); expect(hw.get("min_days")).toBe("3");
    const hr = buildQuery(pt, { start: 1991, end: 2020 }, def, "heavy_rainfall").query;
    expect(hr.get("hazard")).toBe("heavy_rainfall"); expect(hr.get("min_days")).toBeNull();
    const dr = buildQuery(pt, { start: 1991, end: 2020 }, def, "drought").query;
    expect(dr.get("hazard")).toBe("drought"); expect(dr.get("percentile")).toBeNull();
  });
  it("rejects unknown hazards and bad definition values", () => {
    expect(buildQuery(pt, { start: 1991, end: 2020 }, def, "flood").error).toBeTruthy();
    expect(buildQuery(pt, { start: 1991, end: 2020 }, { percentile: 50, minDays: 3 }).error).toMatch(/Percentile/);
    expect(buildQuery(pt, { start: 1991, end: 2020 }, { percentile: 95, minDays: 1 }).error).toMatch(/Minimum days/);
    expect(buildQuery(pt, { start: 1991, end: 2020 }, { percentile: "", minDays: 3 }, "heavy_rainfall").error).toBeTruthy();
    expect(buildQuery(pt, { start: 1991, end: 2020 }, { percentile: "", minDays: "" }, "drought").error).toBeUndefined();
  });
});

describe("buildApiUrl & centralized API client", () => {
  const RENDER_URL = "https://heatwave-trend-analyzer.onrender.com";

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("resolves relative path when VITE_API_URL is unset", () => {
    expect(buildApiUrl("/api/analysis?lat=28.61", "")).toBe("/api/analysis?lat=28.61");
  });

  it("resolves full Render URL correctly", () => {
    expect(buildApiUrl("/api/analysis?lat=28.61", RENDER_URL))
      .toBe("https://heatwave-trend-analyzer.onrender.com/api/analysis?lat=28.61");
  });

  it("handles base URL with trailing slash without duplication", () => {
    expect(buildApiUrl("/api/analysis?lat=28.61", `${RENDER_URL}/`))
      .toBe("https://heatwave-trend-analyzer.onrender.com/api/analysis?lat=28.61");
  });

  it("handles base URL with trailing /api or /api/ without duplicating /api", () => {
    expect(buildApiUrl("/api/analysis?lat=28.61", `${RENDER_URL}/api`))
      .toBe("https://heatwave-trend-analyzer.onrender.com/api/analysis?lat=28.61");
    expect(buildApiUrl("/api/analysis?lat=28.61", `${RENDER_URL}/api/`))
      .toBe("https://heatwave-trend-analyzer.onrender.com/api/analysis?lat=28.61");
  });

  it("normalizes paths missing leading slash or missing /api prefix", () => {
    expect(buildApiUrl("api/analysis?lat=28.61", RENDER_URL))
      .toBe("https://heatwave-trend-analyzer.onrender.com/api/analysis?lat=28.61");
    expect(buildApiUrl("analysis?lat=28.61", RENDER_URL))
      .toBe("https://heatwave-trend-analyzer.onrender.com/api/analysis?lat=28.61");
  });

  it("preserves external full URLs", () => {
    expect(buildApiUrl("https://example.com/api/test", RENDER_URL)).toBe("https://example.com/api/test");
  });

  it("apiUrl is an alias to buildApiUrl", () => {
    expect(apiUrl).toBe(buildApiUrl);
  });

  it("generates correct export URLs for yearly CSV, events CSV, and PDF report", () => {
    const q = "lat=28.61&lon=77.21&hazard=heatwave";
    // Using import.meta.env default
    const yearly = exportUrl("yearly", q);
    const events = exportUrl("events", q);
    const pdf = exportUrl("pdf", q);

    expect(yearly).toContain("/api/export/csv?kind=yearly&lat=28.61&lon=77.21&hazard=heatwave");
    expect(events).toContain("/api/export/csv?kind=events&lat=28.61&lon=77.21&hazard=heatwave");
    expect(pdf).toContain("/api/export/pdf?lat=28.61&lon=77.21&hazard=heatwave");
  });

  it("fetchAnalysis sends request to the resolved API URL", async () => {
    const mockJson = { ok: true, yearly: [] };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockJson,
    });

    const res = await fetchAnalysis("lat=28.61&lon=77.21");
    expect(fetchSpy).toHaveBeenCalled();
    const calledUrl = fetchSpy.mock.calls[0][0];
    expect(calledUrl).toMatch(/\/api\/analysis\?lat=28\.61&lon=77\.21$/);
    expect(res).toEqual(mockJson);
  });

  it("searchPlaces sends request to geocode endpoint", async () => {
    const mockJson = { results: [{ name: "Delhi", lat: 28.61, lon: 77.21 }] };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockJson,
    });

    const res = await searchPlaces("Delhi");
    expect(fetchSpy).toHaveBeenCalled();
    const calledUrl = fetchSpy.mock.calls[0][0];
    expect(calledUrl).toMatch(/\/api\/geocode\?q=Delhi$/);
    expect(res).toEqual(mockJson);
  });

  it("fetchHealth and fetchHazards call their respective endpoints", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: "ok" }),
    });

    await fetchHealth();
    expect(fetchSpy.mock.calls[0][0]).toMatch(/\/api\/health$/);

    await fetchHazards();
    expect(fetchSpy.mock.calls[1][0]).toMatch(/\/api\/hazards$/);
  });
});
