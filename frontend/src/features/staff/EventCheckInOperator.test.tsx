import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  wipeOfflineState: vi.fn(async () => undefined),
}));

vi.mock("./eventCheckInOfflineStore", () => ({
  wipeOfflineState: mocks.wipeOfflineState,
}));
vi.mock("./EventCheckInScanner", () => ({
  default: () => <div>online scanner active</div>,
}));
vi.mock("./OfflineCheckInOperator", () => ({
  OfflineCheckInOperator: () => <div>offline operator active</div>,
}));
vi.mock("./EventStationSettings", () => ({
  EventStationSettings: () => <div>station settings active</div>,
}));

import { EventCheckInOperator } from "./EventCheckInOperator";

function renderOperator(offlineEnabled: boolean) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <EventCheckInOperator
        makerspaceId={11}
        eventId={29}
        offlineEnabled={offlineEnabled}
      />
    </QueryClientProvider>,
  );
}

describe("EventCheckInOperator feature boundary", () => {
  it("keeps online scanning but hides and wipes offline authority when disabled", async () => {
    renderOperator(false);

    expect(screen.getByRole("button", { name: "Scan online" })).toBeInTheDocument();
    expect(screen.queryByText("offline operator active")).not.toBeInTheDocument();
    expect(screen.queryByText("station settings active")).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.wipeOfflineState).toHaveBeenCalledWith("staff:29"));
  });

  it("shows both offline check-in and station controls when enabled", () => {
    renderOperator(true);

    expect(screen.getByRole("button", { name: "Scan online" })).toBeInTheDocument();
    expect(screen.getByText("offline operator active")).toBeInTheDocument();
    expect(screen.getByText("station settings active")).toBeInTheDocument();
  });
});
