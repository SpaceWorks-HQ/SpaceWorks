import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { staffRequest } from "../../lib/api";
import { BookableSpaceForm, EMPTY_SPACE_FORM } from "./BookableSpaceForm";
import type { BookableSpacePayload } from "./bookingsApi";

vi.mock("../../lib/api", () => ({ staffRequest: vi.fn() }));
vi.mock("../forms/CustomFormBuilder", () => ({ CustomFormBuilder: () => null }));

function show(onSubmit: (payload: BookableSpacePayload) => void) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <BookableSpaceForm makerspaceId={2} initialValues={{ ...EMPTY_SPACE_FORM, name: "Laser bench", machine_type: 9 }}
      onSubmit={onSubmit} pending={false} submitLabel="Save space" />
  </QueryClientProvider>);
}

describe("booking editor training link", () => {
  it("omits an unchanged link when Machines discovery is unavailable", async () => {
    vi.mocked(staffRequest).mockRejectedValue(new Error("Module disabled"));
    const submit = vi.fn();
    show(submit);
    expect(await screen.findByText(/Machine type choices are unavailable/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Updated bench" } });
    fireEvent.click(screen.getByText("Save space"));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ name: "Updated bench" }));
    expect(submit.mock.calls[0][0]).not.toHaveProperty("machine_type");
  });

  it("sends an explicit null when the training link is cleared", async () => {
    vi.mocked(staffRequest).mockRejectedValue(new Error("Module disabled"));
    const submit = vi.fn();
    show(submit);
    await screen.findByText(/Machine type choices are unavailable/);
    fireEvent.change(screen.getByRole("combobox", { name: /Machine type for certification/ }), { target: { value: "" } });
    fireEvent.click(screen.getByText("Save space"));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ machine_type: null }));
  });
});
