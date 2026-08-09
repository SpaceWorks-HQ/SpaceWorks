import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CollapsibleSection } from "./CollapsibleSection";

function renderSection(open: boolean, onToggle = vi.fn()) {
  return render(
    <CollapsibleSection title="3D Printers" count={3} open={open} onToggle={onToggle}>
      <button type="button">Prusa MK4</button>
    </CollapsibleSection>,
  );
}

describe("CollapsibleSection", () => {
  it("exposes the open state to assistive tech and points at the region it controls", () => {
    renderSection(true);
    const header = screen.getByRole("button", { name: /3D Printers/ });

    expect(header).toHaveAttribute("aria-expanded", "true");
    // Without aria-controls the announced state is not tied to anything.
    expect(header.getAttribute("aria-controls")).toBeTruthy();
  });

  it("reports collapsed state and removes the contents from the tab order", () => {
    renderSection(false);
    const header = screen.getByRole("button", { name: /3D Printers/ });

    expect(header).toHaveAttribute("aria-expanded", "false");
    // Hidden-but-present rows are a focus trap: a keyboard user tabs into
    // controls they cannot see.
    expect(screen.queryByRole("button", { name: "Prusa MK4" })).toBeNull();
  });

  it("keeps the contents reachable while open", () => {
    renderSection(true);

    expect(screen.getByRole("button", { name: "Prusa MK4" })).toBeTruthy();
  });

  it("toggles on click", () => {
    const onToggle = vi.fn();
    renderSection(true, onToggle);

    fireEvent.click(screen.getByRole("button", { name: /3D Printers/ }));

    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("announces the count as a labelled quantity rather than a bare number", () => {
    renderSection(true);

    expect(screen.getByRole("button", { name: /3 items/ })).toBeTruthy();
  });
});
