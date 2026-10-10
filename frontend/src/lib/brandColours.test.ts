import { describe, expect, it } from "vitest";
import { contrast, tenantColourStyle, type BrandTokens } from "./brandColours";

const light: BrandTokens = {
  fillText: [90, 22, 51], defaultFill: [249, 168, 212],
  surfaces: [[250, 249, 244], [239, 238, 233], [255, 255, 255]],
};
const dark: BrandTokens = { ...light, surfaces: [[22, 22, 28], [38, 40, 51], [29, 30, 38]] };

describe("tenant colours", () => {
  it("applies an AA fill and ink to public/member secondary tokens only", () => {
    expect(tenantColourStyle({ primary_color: "#f3c3dd", accent_color: "#5a1633" }, light)).toEqual({
      "--color-secondary": "243 195 221", "--color-secondary-ink": "90 22 51",
    });
  });
  it("falls back independently for text with poor contrast", () => {
    expect(tenantColourStyle({ primary_color: "#000", accent_color: "#fff" }, light)).toEqual({});
    expect(tenantColourStyle({ primary_color: "#fff", accent_color: "#fff" }, light)).toEqual({
      "--color-secondary": "255 255 255",
    });
  });
  it("rechecks standalone ink against dark surfaces while keeping fixed fill text", () => {
    expect(tenantColourStyle({ primary_color: "#fff", accent_color: "#000" }, dark)).toEqual({
      "--color-secondary": "255 255 255",
    });
    expect(tenantColourStyle({ accent_color: "#fff" }, dark)).toEqual({ "--color-secondary-ink": "255 255 255" });
  });
  it("checks tinted surfaces as well as neutral backgrounds", () => {
    // #757575 clears AA on white but falls short on a pink-tinted white surface.
    expect(contrast([117, 117, 117], [255, 255, 255])).toBeGreaterThanOrEqual(4.5);
    expect(tenantColourStyle({ accent_color: "#757575" }, { ...light, surfaces: [[255, 255, 255]] })).toEqual({});
  });
  it("drops invalid legacy values and clears overrides for the next tenant", () => {
    expect(tenantColourStyle({ primary_color: "url(evil)", accent_color: "red" }, light)).toEqual({});
    expect(tenantColourStyle({}, light)).toEqual({});
  });
  it("protects the 80% opacity counter text on solid fills", () => {
    const candidate: [number, number, number] = [160, 160, 160];
    expect(contrast(candidate, light.fillText)).toBeGreaterThanOrEqual(4.5);
    expect(tenantColourStyle({ primary_color: "#a0a0a0" }, light)).toEqual({});
  });
});
