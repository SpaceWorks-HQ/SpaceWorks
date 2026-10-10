import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BookableSpaceForm } from "./BookableSpaceForm";
import { StaffBookingForm } from "./StaffBookingForm";
import type { BookableSpace } from "./bookingsApi";

const { create, getTypes } = vi.hoisted(() => ({ create: vi.fn(), getTypes: vi.fn() }));
vi.mock("./staffBookingApi", () => ({
  useBookingEligibleMembers: () => ({ data: { results: [{ member_id: 8, display_name: "Ada" }], next: null, previous: null }, isLoading: false, error: null }),
  useStaffCreateBooking: () => ({ mutate: create, isPending: false, isSuccess: false, error: null }),
  getBookingMachineTypes: getTypes,
}));

const space = { id: 4, makerspace_id: 2, machine_type: 9, custom_form: null } as BookableSpace;

beforeEach(() => {
  create.mockReset();
  getTypes.mockReset();
  getTypes.mockResolvedValue({ count: 1, next: null, previous: null, results: [{ id: 9, name: "Laser" }] });
});

describe("Staff booking access controls", () => {
  it("submits a selected member, UTC times and accountable certification override", () => {
    render(<StaffBookingForm makerspaceId={2} space={space} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Member" }), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("Starts (your local time)"), { target: { value: "2026-11-01T14:00" } });
    fireEvent.change(screen.getByLabelText("Ends (your local time)"), { target: { value: "2026-11-01T15:00" } });
    fireEvent.change(screen.getByLabelText(/Certification override reason/), { target: { value: "Observed training" } });
    fireEvent.click(screen.getByRole("button", { name: "Create booking" }));
    expect(create).toHaveBeenCalledWith({
      member_id: 8, starts_at: new Date("2026-11-01T14:00").toISOString(),
      ends_at: new Date("2026-11-01T15:00").toISOString(), note: "",
      certification_override_reason: "Observed training",
    }, expect.any(Object));
  });

  it("requires a member selection and omits override input for unlinked spaces", () => {
    render(<StaffBookingForm makerspaceId={2} space={{ ...space, machine_type: null }} />);
    expect(screen.getByRole("button", { name: "Create booking" })).toBeDisabled();
    expect(screen.queryByLabelText(/Certification override reason/)).not.toBeInTheDocument();
  });

  it("binds a machine type through the space editor and keeps approval under rules", async () => {
    const submit = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><BookableSpaceForm makerspaceId={2} onSubmit={submit} pending={false} submitLabel="Save" /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByRole("option", { name: "Laser" })).toBeInTheDocument());
    expect(getTypes).toHaveBeenCalledWith(2, 1);
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Laser room" } });
    fireEvent.change(screen.getByLabelText(/Machine type for certification/), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ machine_type: 9 }));
    expect(submit.mock.calls[0][0]).not.toHaveProperty("approval_mode");
    expect(screen.queryByRole("combobox", { name: "Approval mode" })).not.toBeInTheDocument();
  });

  it("pages through type choices without losing the selected type", async () => {
    getTypes.mockImplementation((_id: number, page: number) => Promise.resolve({
      count: 25, next: page === 1 ? "next" : null, previous: page === 2 ? "previous" : null,
      results: page === 1 ? [{ id: 9, name: "Laser" }] : [{ id: 10, name: "CNC" }],
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><BookableSpaceForm makerspaceId={2} onSubmit={vi.fn()} pending={false} submitLabel="Save" /></QueryClientProvider>);
    await screen.findByRole("option", { name: "Laser" });
    fireEvent.change(screen.getByLabelText(/Machine type for certification/), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Next types" }));
    await screen.findByRole("option", { name: "CNC" });
    expect(getTypes).toHaveBeenCalledWith(2, 2);
    expect(screen.getByLabelText(/Machine type for certification/)).toHaveValue("9");
    fireEvent.click(screen.getByRole("button", { name: "Previous types" }));
    await screen.findByRole("option", { name: "Laser" });
    expect(screen.getByLabelText(/Machine type for certification/)).toHaveValue("9");
  });
});
