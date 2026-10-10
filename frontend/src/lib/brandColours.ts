import type { CSSProperties } from "react";

type RGB = [number, number, number];
export type BrandTokens = { fillText: RGB; surfaces: RGB[]; defaultFill: RGB };

function rgb(value: unknown): RGB | null {
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

export function tenantColourStyle(theme: Record<string, string>, tokens: BrandTokens): CSSProperties {
  const style: Record<string, string> = {};
  const primary = rgb(theme.primary_color);
  // Catalogue counters use on-secondary/80 on the active fill. Checking the
  // blended text also protects them when an opaque foreground barely clears AA.
  const counterText = primary?.map((c, i) => tokens.fillText[i] * 0.8 + c * 0.2) as RGB | undefined;
  const fill = primary && counterText && contrast(primary, tokens.fillText) >= 4.5
    && contrast(primary, counterText) >= 4.5 ? primary : tokens.defaultFill;
  if (fill === primary) style["--color-secondary"] = fill.join(" ");
  const accent = rgb(theme.accent_color);
  // Secondary ink also appears on /15 tints. Check both the neutral surfaces
  // and those blended backgrounds, in the currently rendered light/dark mode.
  const backgrounds = tokens.surfaces.flatMap((surface) => [surface,
    ...[0.1, 0.15].map((alpha) => surface.map((c, i) => c * (1 - alpha) + fill[i] * alpha) as RGB)]);
  if (accent && backgrounds.every((bg) => contrast(accent, bg) >= 4.5)) {
    style["--color-secondary-ink"] = accent.join(" ");
  }
  // All other tokens (staff accent, fixed text on fills, status and focus) stay
  // inherited. Omitted overrides restore the default when changing tenants.
  return style as CSSProperties;
}

export function readBrandTokens(): BrandTokens | null {
  const css = getComputedStyle(document.documentElement);
  function token(name: string): RGB | null {
    const channels = css.getPropertyValue(`--color-${name}`).trim().split(/\s+/).map(Number);
    return channels.length === 3 && channels.every(Number.isFinite) ? channels as RGB : null;
  }
  const fillText = token("on-secondary"), defaultFill = token("secondary");
  const surfaces = [token("bg"), token("surface"), token("panel")];
  if (!fillText || !defaultFill || surfaces.some((value) => value === null)) return null;
  return { fillText, defaultFill, surfaces: surfaces as RGB[] };
}
