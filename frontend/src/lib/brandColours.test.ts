import { describe, expect, it } from "vitest";
import { BRAND_SURFACES, brandContrastReport, contrast, deriveBrandPalette, rgb, tenantColourStyle, type BrandTokens } from "./brandColours";

const light: BrandTokens = { fillText: [90, 22, 51], defaultFill: [249, 168, 212], surfaces: BRAND_SURFACES.light };
const dark: BrandTokens = { ...light, surfaces: BRAND_SURFACES.dark };

describe("tenant colours", () => {
  it("uses WCAG sRGB transfer and expands shorthand colours", () => {
    expect(contrast([0, 0, 0], [255, 255, 255])).toBe(21);
    expect(contrast([255, 255, 255], [0, 0, 0])).toBe(21);
    expect(contrast([100, 100, 100], [100, 100, 100])).toBe(1);
    expect(contrast([117, 117, 117], [255, 255, 255])).toBeCloseTo(4.6075, 4);
    expect(rgb("#aBc")).toEqual([170, 187, 204]);
    expect(rgb("#ffffff\n")).toBeNull();
  });
  it.each(["#000", "#fff", "#f3c3dd", "#004400", "#abc"])("derives an AA palette for %s in both modes", (primary_color) => {
    const report = brandContrastReport({ primary_color, accent_color: "#5a1633" });
    expect(report.valid).toBe(true);
    expect(report.pairs.every(({ ratio, minimum }) => ratio >= minimum)).toBe(true);
  });
  it("automatically chooses white on a dark fill and black on a light fill", () => {
    expect(tenantColourStyle({ primary_color: "#000" }, light)["--color-on-secondary" as keyof React.CSSProperties]).toBe("255 255 255");
    expect(tenantColourStyle({ primary_color: "#fff" }, dark)["--color-on-secondary" as keyof React.CSSProperties]).toBe("0 0 0");
  });
  it("derives distinct hover and active fills with the same accessible foreground", () => {
    const palette = deriveBrandPalette({ primary_color: "#004400" }, "light");
    expect(palette.fill).toEqual([0, 68, 0]);
    expect(palette.hover).toEqual([0, 63, 0]);
    expect(palette.active).toEqual([0, 57, 0]);
    expect(palette.foreground).toEqual([255, 255, 255]);
  });
  it("derives link ink in each mode on neutral and tinted surfaces", () => {
    const theme = { primary_color: "#f3c3dd", accent_color: "#5a1633" };
    const day = deriveBrandPalette(theme, "light"), night = deriveBrandPalette(theme, "dark");
    expect(day.fill).toEqual(night.fill);
    expect(day.foreground).toEqual(night.foreground);
    expect(day.ink).toEqual([90, 22, 51]);
    // Golden values also asserted by the backend to keep rounding/derivation aligned.
    expect(night.ink).toEqual([194, 169, 180]);
    expect(night.pairs.filter((pair) => pair.pair.includes("tint")).every((pair) => pair.ratio >= 4.5)).toBe(true);
  });
  it("names failures for translucent counter text instead of accepting opaque AA alone", () => {
    expect(contrast([119, 119, 119], [0, 0, 0])).toBeGreaterThan(4.5);
    const report = brandContrastReport({ primary_color: "#777" });
    expect(report.valid).toBe(false);
    expect(report.failures).toEqual(expect.arrayContaining([expect.objectContaining({ mode: "light", pair: "on-secondary/80 on secondary", minimum: 4.5 })]));
  });
  it("falls back as a whole for invalid legacy palettes and empty configuration", () => {
    const invalid: Record<string, string>[] = [{ primary_color: "#777", accent_color: "#000" }, { primary_color: "url(evil)" }, { accent_color: "red" }, {}];
    for (const theme of invalid) {
      expect(tenantColourStyle(theme, light)).toEqual({});
      expect(tenantColourStyle(theme, dark)).toEqual({});
    }
  });
  it("overrides secondary tokens only, preserving staff, status and focus colours", () => {
    expect(Object.keys(tenantColourStyle({ primary_color: "#fff" }, light))).toEqual([
      "--color-secondary", "--color-on-secondary", "--color-secondary-ink", "--color-secondary-hover", "--color-secondary-active", "--color-secondary-boundary",
      "--brand-tint-10-alpha", "--brand-tint-15-alpha",
    ]);
  });
  it("reduces tint strength to preserve ordinary and muted body text", () => {
    const palette = deriveBrandPalette({ primary_color: "#fff" }, "dark");
    expect(palette.tintAlphas[0]).toBeCloseTo(.048);
    expect(palette.tintAlphas[1]).toBeCloseTo(.048);
    expect(palette.pairs.filter((pair) => pair.pair.startsWith("muted on")).every((pair) => pair.ratio >= 4.5)).toBe(true);
  });
  it.each([null, [], "#fff", { primary_color: 0, accent_color: "#fff" }, { primary_color: null, accent_color: "#fff" }, { accent_color: false }])("falls back for malformed restored colour values: %j", (theme) => {
    expect(brandContrastReport(theme).valid).toBe(false);
    expect(tenantColourStyle(theme, light)).toEqual({});
    expect(tenantColourStyle(theme, dark)).toEqual({});
  });
  it("keeps secondary links readable on fixed identity tints and semantic inks on brand tints", () => {
    const palette = deriveBrandPalette({ primary_color: "#f3c3dd", accent_color: "#5a1633" }, "dark");
    const mintOnPanel: [number, number, number] = [29 * .85 + 116 * .15, 30 * .85 + 221 * .15, 38 * .85 + 156 * .15];
    expect(contrast(palette.ink, mintOnPanel)).toBeGreaterThanOrEqual(4.5);
    expect(palette.pairs.find((pair) => pair.pair === "danger on panel/15 tint")?.ratio).toBeGreaterThanOrEqual(4.5);
  });
});
