import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import React from "react";
import fs from "node:fs";
import { THEMES, DEFAULT_THEME, themeFor, chartPalette, rgba } from "./theme.js";
import Stripes from "./components/Stripes.jsx";

const HAZARDS = ["heatwave", "heavy_rainfall", "drought"];

// --- contrast helpers (same maths as the WCAG definition) ---
const chan = (h) => {
  const s = h.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(s.slice(i, i + 2), 16));
};
const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
const lum = (h) => { const [r, g, b] = chan(h); return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b); };
const contrast = (a, b) => {
  const l1 = lum(a), l2 = lum(b);
  const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
};

const yearly = Array.from({ length: 12 }, (_, i) => ({
  year: 2000 + i, events: i, heatwave_days: i * 2, reliable: true, coverage: 1,
}));
const eventYearly = [{ year: 2001, events: 1, heavy_days: 3, reliable: true, coverage: 1 }];
const droughtYearly = [{ year: 2001, events: 1, drought_months: 2, reliable: true, coverage: 1 }];

describe("theme lookup", () => {
  it("has an entry for every hazard the API offers", () => {
    for (const h of HAZARDS) expect(THEMES[h]).toBeDefined();
  });
  it("falls back to the default for an unknown hazard", () => {
    expect(themeFor("nonsense")).toBe(DEFAULT_THEME);
    expect(themeFor(undefined)).toBe(DEFAULT_THEME);
  });
  it("gives each hazard a distinct accent", () => {
    const accents = HAZARDS.map((h) => THEMES[h].accent);
    expect(new Set(accents).size).toBe(HAZARDS.length);
  });
});

describe("accessibility of every theme", () => {
  for (const h of HAZARDS) {
    const t = THEMES[h];
    it(`${h}: accent passes WCAG AA where it is used`, () => {
      expect(contrast(t.accent, "#F2F4F5")).toBeGreaterThanOrEqual(3);   // h1, large text on page bg
      expect(contrast("#FFFFFF", t.accent)).toBeGreaterThanOrEqual(4.5); // button label
      expect(contrast("#FFFFFF", t.accentDark)).toBeGreaterThanOrEqual(4.5); // button hover label
      expect(contrast(t.accentDark, "#FFFFFF")).toBeGreaterThanOrEqual(4.5);   // h2, table headers, KPI figures
    });
    it(`${h}: ramp descends in luminance and ends dark enough`, () => {
      const L = t.ramp.map(lum);
      for (let i = 1; i < L.length; i++) expect(L[i]).toBeLessThan(L[i - 1]);
      expect(contrast(t.ramp[t.ramp.length - 1], "#FFFFFF")).toBeGreaterThanOrEqual(3);
    });
    it(`${h}: trend line is a different hue from the bars`, () => {
      expect(t.trend.toUpperCase()).not.toBe(t.accent.toUpperCase());
      expect(contrast(t.trend, "#FFFFFF")).toBeGreaterThanOrEqual(3);
    });
    it(`${h}: every colour is a valid hex`, () => {
      for (const c of [t.accent, t.accentDark, t.trend, ...t.ramp, ...t.excluded]) {
        expect(c).toMatch(/^#[0-9A-Fa-f]{6}$/);
      }
    });
  }
});

const css = fs.readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const ruleFor = (sel) => {
  const m = css.match(new RegExp(`(?:^|\\n)\\s*${sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{([^}]*)\\}`));
  return m ? m[1] : null;
};

describe("tables and charts are styled as cards", () => {
  it("both sit on the same elevation as the panel and hero", () => {
    // --shadow-sm is reserved for inline controls; content surfaces use --shadow-md.
    for (const sel of [".chart-card", ".table-scroll", ".kpis div", ".hero", ".panel"]) {
      const body = ruleFor(sel);
      expect(body, `${sel} not found in styles.css`).toBeTruthy();
      expect(body, `${sel} should use --shadow-md`).toContain("var(--shadow-md)");
      expect(body, `${sel} should not use --shadow-sm`).not.toContain("--shadow-sm");
    }
  });
  it("tables and charts share a 6px radius", () => {
    expect(ruleFor(".chart-card")).toContain("border-radius: 6px");
    expect(ruleFor(".table-scroll")).toContain("border-radius: 6px");
  });
  it("a themed accent bar ties each card to the hazard", () => {
    for (const sel of [".chart-card", ".table-scroll"]) {
      expect(ruleFor(sel), `${sel} should carry the accent bar`).toContain("border-top: 3px solid var(--accent)");
    }
  });
  it("both lift to the raised shadow on hover", () => {
    expect(ruleFor(".chart-card:hover")).toContain("var(--shadow-lg)");
    expect(ruleFor(".table-scroll:hover")).toContain("var(--shadow-lg)");
    expect(ruleFor(".chart-card:hover")).toContain("translateY(-1px)");
  });
  it("the table still scrolls horizontally and clips its rounded header", () => {
    const body = ruleFor(".table-scroll");
    expect(body).toContain("overflow-x: auto");
  });
  it("hover lift is disabled for reduced-motion users", () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
  });
});

describe("chartPalette", () => {
  it("derives a translucent bar fill that matches the accent", () => {
    for (const h of HAZARDS) {
      const t = THEMES[h];
      const [r, g, b] = chan(t.accent);
      expect(chartPalette(t).bar).toBe(`rgba(${r},${g},${b},0.78)`);
      expect(chartPalette(t).line.toUpperCase()).toBe(t.accent.toUpperCase());
    }
  });
  it("rgba parses 3- and 6-digit hex", () => {
    expect(rgba("#abc", 0.5)).toBe("rgba(170,187,204,0.5)");
  });
});

describe("Stripes uses the theme ramp", () => {
  const cases = [
    ["heatwave", yearly, "heatwave_days"],
    ["heavy_rainfall", eventYearly, "heavy_days"],
    ["drought", droughtYearly, "drought_months"],
  ];
  for (const [hazard, rows, field] of cases) {
    it(`${hazard}: renders the ramp swatches and colours bars from that theme`, () => {
      const t = THEMES[hazard];
      const html = renderToStaticMarkup(
        React.createElement(Stripes, { yearly: rows, field, label: field, theme: t })
      );
      for (const c of t.ramp) expect(html).toContain(c);
      // no other hazard's ramp may leak in
      for (const other of HAZARDS.filter((h) => h !== hazard)) {
        for (const c of THEMES[other].ramp) {
          if (!t.ramp.includes(c)) expect(html).not.toContain(c);
        }
      }
    });
  }

  it("still renders without a theme prop (backwards compatible)", () => {
    const html = renderToStaticMarkup(React.createElement(Stripes, { yearly, field: "heatwave_days" }));
    expect(html).toContain(DEFAULT_THEME.ramp[0]);
  });
});