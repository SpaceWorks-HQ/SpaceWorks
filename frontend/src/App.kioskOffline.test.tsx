import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./lib/tenant", () => ({ useTenant: () => ({ mode: "single", loading: true, error: null }) }));
vi.mock("./features/kiosk/KioskStationPage", () => ({ KioskStationPage: () => <p>Cached Station shell</p> }));
vi.mock("./AppRoutes", () => ({ AppRoutes: () => <p>Other route</p> }));
vi.mock("./features/LandingPage", () => ({ LandingPage: () => <p>Landing</p> }));
it("opens a UUID Station shell while tenant bootstrap is unavailable", async () => {
  render(<MemoryRouter initialEntries={["/kiosk/00000000-0000-0000-0000-000000000001"]}><App /></MemoryRouter>);
  expect(await screen.findByText("Cached Station shell")).toBeTruthy();
});
it("preserves bootstrap gating for ordinary tenant routes", () => {
  render(<MemoryRouter initialEntries={["/member"]}><App /></MemoryRouter>);
  expect(screen.getByText("Loading site...")).toBeTruthy();
});
