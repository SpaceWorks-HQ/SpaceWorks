import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { expect, it } from "vitest";
import { MemberPortalTabs, useMemberTab } from "./MemberPortalTabs";
import { expectNoA11yViolations } from "../../test/axe";

const modules = ["membership", "request_workflow", "bookings", "events"];
function Harness({ enabled = modules }: { enabled?: string[] }) {
  const active = useMemberTab(enabled);
  const location = useLocation();
  const navigate = useNavigate();
  return <main><MemberPortalTabs modules={enabled} active={active}><h1>{active} content</h1></MemberPortalTabs><output>{location.pathname}</output><button onClick={() => navigate(-1)}>Back</button></main>;
}

it.each(["/member", "/m/lab/member", "/m/member/member", "/m/member-tools/member"])("deep links, tab navigation and Back work under %s", (base) => {
  render(<MemoryRouter initialEntries={[`${base}/bookings`]}><Harness /></MemoryRouter>);
  expect(screen.getByRole("tab", { name: "Bookings" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Bookings");
  expect(screen.getByRole("tabpanel")).toHaveAttribute("tabindex", "-1");
  fireEvent.click(screen.getByRole("tab", { name: "Events" }));
  expect(screen.getByText(`${base}/events`)).toBeVisible();
  expect(screen.queryByText("bookings content")).toBeNull();
  fireEvent.click(screen.getByText("Back"));
  expect(screen.getByText("bookings content")).toBeVisible();
});

it("supports arrow keys, Home and End with a single tab stop", async () => {
  const view = render(<MemoryRouter initialEntries={["/m/lab/member"]}><Harness /></MemoryRouter>);
  const overview = screen.getByRole("tab", { name: "Overview" });
  overview.focus();
  fireEvent.keyDown(overview, { key: "ArrowRight" });
  expect(screen.getByRole("tab", { name: "Loans" })).toHaveFocus();
  expect(screen.getByText("loans content")).toBeVisible();
  fireEvent.keyDown(document.activeElement!, { key: "End" });
  expect(screen.getByRole("tab", { name: "Account" })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
  expect(overview).toHaveFocus();
  fireEvent.keyDown(overview, { key: "ArrowLeft" });
  expect(screen.getByRole("tab", { name: "Account" })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "Home" });
  expect(overview).toHaveFocus();
  expect(screen.getAllByRole("tab").filter((tab) => tab.tabIndex === 0)).toHaveLength(1);
  await expectNoA11yViolations(view.container);
});

it("hides module-dependent tabs but keeps account-only payments reachable", () => {
  render(<MemoryRouter initialEntries={["/m/lab/member/loans"]}><Harness enabled={[]} /></MemoryRouter>);
  expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Overview", "Payments", "Account"]);
  expect(screen.getByText("overview content")).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: "Payments" }));
  expect(screen.getByText("payments content")).toBeVisible();
});

it("keeps invalid tab names from becoming part of the portal base URL", () => {
  render(<MemoryRouter initialEntries={["/m/member/member/member"]}><Harness /></MemoryRouter>);
  expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  fireEvent.click(screen.getByRole("tab", { name: "Account" }));
  expect(screen.getByText("/m/member/member/account-portal")).toBeVisible();
});
