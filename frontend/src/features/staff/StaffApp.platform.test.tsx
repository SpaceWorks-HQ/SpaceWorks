import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StaffApp } from "./StaffApp";

const { session } = vi.hoisted(() => ({ session: vi.fn() }));
vi.mock("./useStaffSession", () => ({ useStaffSession: session }));
vi.mock("./StaffWorkspace", () => ({ StaffWorkspace: () => <p>Platform workspace</p> }));
vi.mock("./MakerspacePicker", () => ({ MakerspacePicker: () => <p>Pick a makerspace</p> }));
vi.mock("./StaffAccessDenied", () => ({ StaffAccessDenied: () => <p>Tenant access denied</p> }));

describe("platform dashboard entry", () => {
  beforeEach(() => session.mockReturnValue({
    restoring: false, user: { role: "superadmin", is_superuser: true, makerspaces: [] },
    recovery: { data: null }, makerspaces: { data: [], isLoading: false },
    singleTenantLocked: false, selected: null, tenant: {},
  }));

  it.each([null, 999])("opens without a valid tenant selection (%s)", (selected) => {
    session.mockReturnValue({ ...session(), selected });
    render(<MemoryRouter initialEntries={["/admin/platform-dashboard"]}><StaffApp /></MemoryRouter>);
    expect(screen.getByText("Platform workspace")).toBeInTheDocument();
    expect(screen.queryByText("Pick a makerspace")).not.toBeInTheDocument();
  });

  it("keeps the tenant picker for inventory", () => {
    render(<MemoryRouter initialEntries={["/admin/inventory"]}><StaffApp /></MemoryRouter>);
    expect(screen.getByText("Pick a makerspace")).toBeInTheDocument();
  });

  it("preserves custom-domain tenant access checks", () => {
    session.mockReturnValue({ ...session(), singleTenantLocked: true });
    render(<MemoryRouter initialEntries={["/admin/platform-dashboard"]}><StaffApp /></MemoryRouter>);
    expect(screen.getByText("Tenant access denied")).toBeInTheDocument();
    expect(screen.queryByText("Platform workspace")).not.toBeInTheDocument();
  });
});
