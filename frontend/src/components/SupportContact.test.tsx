import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { SiteFooter } from "./SiteFooter";
import { SupportContact } from "./SupportContact";

describe("support contact", () => {
  it("renders the configured contact links in the public footer", () => {
    render(<MemoryRouter><SiteFooter branding={{ support_email: "help@example.com", support_url: "https://example.com/help" }} /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "help@example.com" })).toHaveAttribute("href", "mailto:help@example.com");
    expect(screen.getByRole("link", { name: "Contact support" })).toHaveAttribute("href", "https://example.com/help");
    expect(screen.getByRole("link", { name: "About" })).toBeVisible();
  });
  it("hides empty configuration", () => {
    const { container } = render(<SupportContact branding={{}} />);
    expect(container).toBeEmptyDOMElement();
  });
  it.each(["javascript:alert(1)", "data:text/html,bad", "https://user:password@example.com"])("refuses an unsafe legacy URL %s", (support_url) => {
    render(<SupportContact branding={{ support_email: "help@example.com?subject=bad", support_url }} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
