/**
 * Per-hazard colour themes.
 *
 * One source of truth for both CSS (via the `data-theme` attribute on the app root)
 * and Chart.js, which needs literal colour values rather than CSS custom properties.
 *
 * Colour choices are not arbitrary: `accent` is used as white-on-colour button fill and as
 * large heading text, so every value below was checked against WCAG AA:
 *   accent  on --paper (large text)      >= 3:1
 *   accentDark on white (normal text)    >= 4.5:1
 *   white on accent (button label)       >= 4.5:1
 * `ramp` must descend in luminance (it encodes "fewer -> more") and its darkest step is
 * the accent family. `trend` is deliberately a *different* hue from the bars so the
 * regression line stays legible on top of them.
 */

const rgba = (hex, a) => {
  let h = hex.replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");   // #abc -> #aabbcc
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return `rgba(${r},${g},${b},${a})`;
};

const THEMES = {
  heatwave: {
    id: "heatwave",
    accent: "#CE440E", // was #D9480F: 4.30:1 with white text, shaded to reach AA
    accentDark: "#8E2A07",
    ramp: ["#FBE9D8", "#F6C390", "#EE8F4B", "#CE440E", "#8E2A07"],
    trend: "#2C6E8F",
    excluded: ["#E3E7EA", "#F6F7F8"],
  },
  heavy_rainfall: {
    id: "heavy_rainfall",
    accent: "#1C6EA4",
    accentDark: "#0D4A70",
    ramp: ["#DEEAF4", "#A9CCE4", "#5EA2CF", "#1C6EA4", "#0B4468"],
    trend: "#B4530A",
    excluded: ["#E3E7EA", "#F6F7F8"],
  },
  drought: {
    id: "drought",
    accent: "#8A5A2B",
    accentDark: "#5A3817",
    ramp: ["#F1E7D9", "#D9C3A3", "#BA966B", "#8A5A2B", "#5A3817"],
    trend: "#2C6E8F",
    excluded: ["#E3E7EA", "#F6F7F8"],
  },
};

export { THEMES };
export const DEFAULT_THEME = THEMES.heatwave;
export const themeFor = (hazard) => THEMES[hazard] ?? DEFAULT_THEME;

/** Chart-facing view of a theme: bar fill, line colours and the grey for unreliable years. */
export const chartPalette = (theme) => ({
  bar: rgba(theme.accent, 0.78),
  line: theme.accent,
  trend: theme.trend,
  rolling: "#16222E",
  unreliable: "#C4CBD0",
});

export { rgba };