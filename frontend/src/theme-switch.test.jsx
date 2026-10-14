// @vitest-environment jsdom
// Real interaction test: change the hazard dropdown and assert the DOM theme attribute
// and the chart/stripe colours actually follow it.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import fs from "node:fs";
import { THEMES } from "./theme.js";

vi.mock("./api.js", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    // The real fetch would hit a network; the theme only cares that data arrives.
    fetchAnalysis: vi.fn(async () => FIXTURE),
    searchPlaces: vi.fn(async () => ({ results: [] })),
  };
});

// Minimal stand-in for Leaflet: enough surface for MapPicker to mount without a real map.
vi.mock("leaflet", () => {
  const layer = () => ({ addTo: () => layer(), remove: () => {}, clearLayers: () => {}, getBounds: () => ({}) });
  const mapObj = () => ({
    setView: () => {}, on: () => {}, remove: () => {}, getZoom: () => 4, fitBounds: () => {},
  });
  return {
    default: {
      map: () => mapObj(),
      tileLayer: () => ({ addTo: () => {} }),
      layerGroup: () => layer(),
      circleMarker: () => layer(),
      rectangle: () => layer(),
      marker: () => layer(),
      latLngBounds: () => ({}),
    },
  };
});
vi.mock("chart.js", () => ({
  Chart: { register: () => {} },
  registerables: [],
  BarController: {}, LineController: {}, BarElement: {}, LineElement: {},
  PointElement: {}, CategoryScale: {}, LinearScale: {}, Tooltip: {}, Legend: {},
}));

const ChartStub = ({ data }) => <div data-testid="chart" data-datasets={JSON.stringify(data.datasets)} />;

// YearChart imports { Chart } (named); other charts may use the default export.
vi.mock("react-chartjs-2", () => ({
  Chart: ChartStub,
  default: ChartStub,
  Bar: ChartStub,
  Line: ChartStub,
}));

const yearly = Array.from({ length: 6 }, (_, i) => ({
  year: 1990 + i, days_in_data: 365, valid_days: 365, coverage: 1, reliable: true,
  events: i, heatwave_days: i * 2, heavy_days: i, drought_months: i,
  max_duration: i, mean_duration: i, mean_intensity_c: 1, max_intensity_c: 2,
  mean_tmax_c: 15, annual_total_mm: 600, rx1day_mm: 30, heavy_total_mm: 100,
  events_rolling5: i, heatwave_days_rolling5: i, heavy_days_rolling5: i, drought_months_rolling5: i,
}));

const FIXTURE = {
  hazard: "heatwave", hazard_label: "Heatwave", definition: "d", main_metric: "heatwave_days",
  main_label: "heatwave days", params: { start_year: 1990, end_year: 1995, percentile: 95, min_days: 3 },
  meta: { source: "test", from_cache: false, quality: { coverage: 1 } },
  thresholds: {}, totals: {}, kpis: [{ value: 1, label: "x" }], stripe: { field: "heatwave_days", label: "heatwave days" },
  charts: [{ title: "Heatwaves per year", field: "events", rolling: "events_rolling5", trend: "events", unit: "events" }],
  event_columns: [{ key: "start", label: "Start" }], event_sort: "start", events_title: "t",
  yearly_columns: [], yearly, events: [], events_truncated: false,
  trends: { events: { status: "insufficient" } },
  insights: [{ level: "headline", text: "h" }], region: { lat: 1, lon: 2, bbox: null },
};

// Tells React we are driving updates manually via act().
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const { default: App } = await import("./App.jsx");

let container, root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

const render = async () => {
  await act(async () => { root.render(<App />); });
};
const pickHazard = async (value) => {
  const sel = container.querySelector('select[aria-label="Hazard type"]');
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value").set.call(sel, value);
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  });
};

// React/jsdom normalises inline colours to "rgb(r, g, b)"; compare numerically.
const asRgb = (s) => {
  const m = s.match(/(\d+)\D+(\d+)\D+(\d+)/);
  return m ? m.slice(1, 4).map(Number) : null;
};
const toRgb = (hex) => hex.replace("#", "").match(/\w\w/g).map((h) => parseInt(h, 16));

describe("hazard switching repaints the page", () => {
  for (const hazard of ["heatwave", "heavy_rainfall", "drought"]) {
    it(`${hazard}: sets data-theme on the app root`, async () => {
      await render();
      await pickHazard(hazard);
      expect(container.querySelector(".app").getAttribute("data-theme")).toBe(hazard);
    });

    it(`${hazard}: stripe ramp uses that theme's colours`, async () => {
      await render();
      await pickHazard(hazard);
      const swatches = [...container.querySelectorAll(".legend i")].map((n) => asRgb(n.style.background));
      const expected = THEMES[hazard].ramp.map(toRgb);
      expect(swatches).toEqual(expected);
    });

    it(`${hazard}: chart bar colour matches the theme accent`, async () => {
      await render();
      await pickHazard(hazard);
      const datasets = JSON.parse(container.querySelector('[data-testid="chart"]').dataset.datasets);
      const bar = datasets.find((d) => d.type === "bar");
      const [r, g, b] = THEMES[hazard].accent.match(/\w\w/g).map((h) => parseInt(h, 16));
      for (const colour of bar.backgroundColor) expect(colour).toBe(`rgba(${r},${g},${b},0.78)`);
    });
  }

  it("moving between two hazards actually changes the rendered colours", async () => {
    await render();
    await pickHazard("heatwave");
    const heatStripe = container.querySelector(".legend i").style.background;
    const heatBar = container.querySelector('[data-testid="chart"]').dataset.datasets;
    await pickHazard("heavy_rainfall");
    const rainStripe = container.querySelector(".legend i").style.background;
    const rainBar = container.querySelector('[data-testid="chart"]').dataset.datasets;
    expect(rainStripe).not.toBe(heatStripe);
    expect(rainBar).not.toBe(heatBar);
  });
});

describe("stylesheet agrees with the JS palettes", () => {
  it("no leftover --heat variable", async () => {
    const css = await import("./styles.css?raw").then((m) => m.default);
    expect(css).not.toMatch(/var\(--heat/);
  });
});