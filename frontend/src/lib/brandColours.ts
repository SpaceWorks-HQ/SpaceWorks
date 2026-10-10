import type { CSSProperties } from "react";

export type RGB = [number, number, number];
export type BrandTokens = { fillText: RGB; surfaces: RGB[]; defaultFill: RGB };
export type ContrastPair = { mode: string; pair: string; ratio: number; minimum: number };
export const BRAND_SURFACES: Record<"light" | "dark", RGB[]> = {
  light: [[250, 249, 244], [239, 238, 233], [255, 255, 255]],
  dark: [[22, 22, 28], [38, 40, 51], [29, 30, 38]],
};
const PRODUCT_FILL: RGB = [249, 168, 212];
const BODY_TEXT: Record<"light" | "dark", RGB[]> = {
  light: [[31, 46, 53], [92, 103, 112]],
  dark: [[236, 234, 242], [154, 160, 173]],
};
const FIXED_INKS: Record<"light" | "dark", RGB[]> = {
  light: [[0, 55, 74], [0, 50, 27], [61, 52, 0], [164, 36, 59]],
  dark: [[125, 211, 252], [116, 221, 156], [252, 223, 70], [244, 114, 127]],
};
const FIXED_FILLS: RGB[] = [[125, 211, 252], [116, 221, 156], [252, 223, 70]];

export function rgb(value: unknown): RGB | null {
  if (typeof value !== "string" || !/^#(?:[\da-f]{3}|[\da-f]{6})$/i.test(value)) return null;
  const hex = value.slice(1);
  const expanded = hex.length === 3 ? [...hex].map((c) => c + c).join("") : hex;
  return [0, 2, 4].map((i) => parseInt(expanded.slice(i, i + 2), 16)) as RGB;
}

function luminance(color: RGB) {
  const linear = color.map((c) => {
    const v = c / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

export function contrast(a: RGB, b: RGB) {
  const x = luminance(a), y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

function blend(a: RGB, b: RGB, amount: number, rounded = true): RGB {
  return a.map((v, i) => {
    const channel = v * (1 - amount) + b[i] * amount;
    return rounded ? Math.round(channel) : channel;
  }) as RGB;
}

// Keep this contract in sync with apps/makerspaces/theme_contrast.py.
export function deriveBrandPalette(theme: Record<string, string>, mode: "light" | "dark", surfaces = BRAND_SURFACES[mode]) {
  const custom = Boolean(theme.primary_color || theme.accent_color);
  const fill = rgb(theme.primary_color) ?? PRODUCT_FILL;
  const black: RGB = [0, 0, 0], white: RGB = [255, 255, 255];
  const foreground: RGB = custom ? (contrast(black, fill) >= contrast(white, fill) ? black : white) : [90, 22, 51];
  const target = foreground === black ? white : black;
  const hover = custom ? blend(fill, target, .08) : fill, active = custom ? blend(fill, target, .16) : fill;
  const names = ["bg", "surface", "panel"];
  // Keep ordinary/muted text readable inside brand tints, without changing the
  // shared text tokens. Composite in floating point exactly as CSS does.
  const tintAlphas = [.1, .15].map((requested) => {
    for (let step = 0; step <= 100; step++) {
      const alpha = requested * (1 - step / 100);
      if ([...BODY_TEXT[mode], ...FIXED_INKS[mode]].every((text) => surfaces.every((surface) => contrast(text, blend(surface, fill, alpha, false)) >= 4.55))) return alpha;
    }
    return 0;
  });
  const backgrounds = surfaces.flatMap((surface, i) => [
    { name: names[i], color: surface },
    { name: `${names[i]}/10 tint`, color: blend(surface, fill, tintAlphas[0], false) },
    { name: `${names[i]}/15 tint`, color: blend(surface, fill, tintAlphas[1], false) },
  ]);
  // Identity-coloured member cards contain secondary links too. Their neutral
  // panel base prevents tint stacking; their fixed pastel tints still need AA.
  const linkBackgrounds = [...backgrounds, ...surfaces.flatMap((surface, i) => FIXED_FILLS.map((color, j) => ({
    name: `${names[i]} with ${["accent", "success", "warn"][j]}/15 tint`, color: blend(surface, color, .15, false),
  })))];
  let ink = rgb(theme.accent_color) ?? fill;
  if (!custom) ink = mode === "light" ? [90, 22, 51] : PRODUCT_FILL;
  const endpoint = mode === "light" ? black : white;
  for (let step = 0; step <= 100; step++) {
    const candidate = blend(ink, endpoint, step / 100);
    if (linkBackgrounds.every(({ color }) => contrast(candidate, color) >= 4.5)) {
      ink = candidate;
      break;
    }
  }
  const pairs: ContrastPair[] = [];
  const add = (pair: string, a: RGB, b: RGB, minimum = 4.5) => pairs.push({ mode, pair, ratio: contrast(a, b), minimum });
  for (const [name, background] of [["secondary", fill], ["secondary-hover", hover], ["secondary-active", active]] as const) {
    add(`on-secondary on ${name}`, foreground, background);
    const counter = foreground.map((c, i) => c * .8 + background[i] * .2) as RGB;
    add(`on-secondary/80 on ${name}`, counter, background);
  }
  linkBackgrounds.forEach(({ name, color }) => add(`secondary-ink on ${name}`, ink, color));
  BODY_TEXT[mode].forEach((text, i) => backgrounds.forEach(({ name, color }) => add(`${i === 0 ? "ink" : "muted"} on ${name}`, text, color)));
  FIXED_INKS[mode].forEach((text, i) => backgrounds.forEach(({ name, color }) => add(`${["accent-ink", "success-ink", "warn-ink", "danger"][i]} on ${name}`, text, color)));
  surfaces.forEach((color, i) => add(`secondary boundary on ${names[i]}`, ink, color, 3));
  return { fill, foreground, hover, active, ink, tintAlphas, pairs };
}

export function brandContrastReport(value: unknown) {
  const theme = value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
  if (!theme) return { errors: ["Theme configuration must be an object."], pairs: [], failures: [], valid: false };
  const errors = ["primary_color", "accent_color"].filter((key) => key in theme && (typeof theme[key] !== "string" || (theme[key] !== "" && !rgb(theme[key]))))
    .map((key) => `${key} must be a #RGB or #RRGGBB colour, or blank.`);
  const pairs = (["light", "dark"] as const).flatMap((mode) => deriveBrandPalette(theme as Record<string, string>, mode).pairs);
  const failures = pairs.filter(({ ratio, minimum }) => ratio < minimum);
  return { errors, pairs, failures, valid: errors.length === 0 && failures.length === 0 };
}

export function tenantColourStyle(value: unknown, tokens: BrandTokens, mode?: "light" | "dark"): CSSProperties {
  // A rejected legacy palette restores ALL product tokens; no partial overrides.
  if (!brandContrastReport(value).valid) return {};
  const theme = value as Record<string, string>;
  if (!theme.primary_color && !theme.accent_color) return {};
  const resolvedMode = mode ?? (luminance(tokens.surfaces[0]) < .5 ? "dark" : "light");
  const palette = deriveBrandPalette(theme, resolvedMode, tokens.surfaces);
  if (palette.pairs.some(({ ratio, minimum }) => ratio < minimum)) return {};
  return brandPaletteStyle(palette);
}

export function brandPaletteStyle(palette: ReturnType<typeof deriveBrandPalette>): CSSProperties {
  return {
    "--color-secondary": palette.fill.join(" "),
    "--color-on-secondary": palette.foreground.join(" "),
    "--color-secondary-ink": palette.ink.join(" "),
    "--color-secondary-hover": palette.hover.join(" "),
    "--color-secondary-active": palette.active.join(" "),
    "--color-secondary-boundary": palette.ink.join(" "),
    "--brand-tint-10-alpha": String(palette.tintAlphas[0]),
    "--brand-tint-15-alpha": String(palette.tintAlphas[1]),
  } as CSSProperties;
}

export function readBrandTokens(): BrandTokens | null {
  const css = getComputedStyle(document.documentElement);
  function token(name: string): RGB | null {
    const channels = css.getPropertyValue(`--color-${name}`).trim().split(/\s+/).map(Number);
    return channels.length === 3 && channels.every((value) => Number.isFinite(value) && value >= 0 && value <= 255) ? channels as RGB : null;
  }
  const fillText = token("on-secondary"), defaultFill = token("secondary");
  const surfaces = [token("bg"), token("surface"), token("panel")];
  if (!fillText || !defaultFill || surfaces.some((value) => value === null)) return null;
  return { fillText, defaultFill, surfaces: surfaces as RGB[] };
}
