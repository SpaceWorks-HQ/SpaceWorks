import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { NotificationRecipientPicker } from "./NotificationRecipientPicker";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));
vi.mock("./NotificationDestinations", () => ({ useScopeOptions: () => ({
  machineTypes: [], machines: [], categories: [],
}) }));
vi.mock("./NotificationRecipientEvent", () => ({
  EventRecipients: ({ feature, event }: { feature: string; event: string }) =>
    <div data-testid="selected-event">{feature}:{event}</div>,
}));

it("labels the new families and changes the selected event to that family's first key", async () => {
  staffRequest.mockResolvedValue({ delegated: false, features: [
    { key: "payments", events: ["charge_raised", "payment_received"] },
    { key: "stock", events: ["low_stock", "procurement_received"] },
    { key: "certifications", events: ["granted", "expiring"] },
  ], roles: [], members: [], rules: [], managed_policy_markers: [],
  scope_options: { machine_types: [], machines: [], categories: [] } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>
    <NotificationRecipientPicker makerspaceId={7} />
  </QueryClientProvider>);
  await screen.findByRole("option", { name: "Payments" });
  expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/notification-recipient-rules");
  const area = screen.getByRole("combobox", { name: "Area" });
  fireEvent.change(area, { target: { value: "stock" } });
  expect(screen.getByRole("option", { name: "Stock and procurement" })).toBeInTheDocument();
  expect(screen.getByTestId("selected-event")).toHaveTextContent("stock:low_stock");
  fireEvent.change(area, { target: { value: "certifications" } });
  expect(screen.getByRole("option", { name: "Certifications" })).toBeInTheDocument();
  expect(screen.getByTestId("selected-event")).toHaveTextContent("certifications:granted");
  expect(screen.queryByRole("option", { name: "payment received" })).not.toBeInTheDocument();
});
