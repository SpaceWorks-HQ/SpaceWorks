import { render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { PageMetadata } from "./PageMetadata";
import { applyTenantBranding } from "../lib/branding";
import type { TenantBootstrap } from "../lib/api";

const content = (property: string) => document.head.querySelector(`meta[property="${property}"]`)?.getAttribute("content");
afterEach(() => { document.head.querySelectorAll('[data-test-shell]').forEach((node) => node.remove()); });

it("sets title, description, canonical and Open Graph using absolute public URLs", () => {
  render(<PageMetadata title="Drill · Lab" description="Public tool" path="/m/lab/items/7" image="/images/drill.jpg" siteName="Lab" />);
  expect(document.title).toBe("Drill · Lab");
  expect(document.head.querySelector('meta[name="description"]')).toHaveAttribute("content", "Public tool");
  expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute("href", `${window.location.origin}/m/lab/items/7`);
  expect(content("og:title")).toBe("Drill · Lab");
  expect(content("og:description")).toBe("Public tool");
  expect(content("og:url")).toBe(`${window.location.origin}/m/lab/items/7`);
  expect(content("og:image")).toBe(`${window.location.origin}/images/drill.jpg`);
  expect(content("og:site_name")).toBe("Lab");
  applyTenantBranding({ makerspace: { name: "Lab" }, branding: {}, theme: {} } as TenantBootstrap);
  expect(document.title).toBe("Drill · Lab");
});

it("updates tags without duplicates and restores the shell metadata on unmount", () => {
  document.title = "Shell";
  const shell = document.createElement("meta");
  shell.name = "description"; shell.content = "Default"; shell.dataset.testShell = "true";
  document.head.appendChild(shell);
  const duplicate = shell.cloneNode() as HTMLMetaElement;
  document.head.appendChild(duplicate);
  const view = render(<PageMetadata title="Lab" description="First" path="/m/lab" image="/logo.png" />);
  view.rerender(<PageMetadata title="Workshop" description="Second" path="/m/workshop" />);
  expect(document.title).toBe("Workshop");
  expect(document.head.querySelectorAll('meta[name="description"]')).toHaveLength(1);
  expect(document.head.querySelectorAll('meta[property="og:title"]')).toHaveLength(1);
  expect(content("og:image")).toBe("");
  view.unmount();
  expect(document.title).toBe("Shell");
  expect(shell.content).toBe("Default");
  expect(duplicate.parentElement).toBe(document.head);
  expect(document.head.querySelector('link[rel="canonical"]')).toBeNull();
  expect(content("og:title")).toBeUndefined();
});

it("does not accept executable image schemes or inject description markup", () => {
  render(<PageMetadata title="Lab" description={'<script>alert("x")</script>'} path="/m/lab" image="javascript:alert(1)" />);
  expect(content("og:image")).toBe("");
  expect(document.head.querySelector('meta[name="description"]')).toHaveAttribute("content", '<script>alert("x")</script>');
  expect(document.head.querySelector("script")).toBeNull();
});
