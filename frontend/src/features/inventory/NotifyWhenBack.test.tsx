import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NotifyWhenBack } from "./NotifyWhenBack";
import { tenantPublicRequest } from "../../lib/api";

vi.mock("../../lib/api", () => ({ tenantPublicRequest: vi.fn() }));
const request = vi.mocked(tenantPublicRequest);

function view() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
    <NotifyWhenBack slug="lab" productId={7} />
  </QueryClientProvider>);
}

describe("availability watch", () => {
  beforeEach(() => { request.mockReset(); });
  it("subscribes the signed-in account with no contact input and cancels", async () => {
    request.mockResolvedValue({ subscribed: true });
    view();
    fireEvent.click(screen.getByRole("button", { name: "Notify me when back" }));
    await screen.findByRole("button", { name: "Cancel notification" });
    expect(request).toHaveBeenCalledWith("lab", "/public/lab/inventory/7/watch/", { method: "POST", body: "{}" });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel notification" }));
    await screen.findByRole("button", { name: "Notify me when back" });
    expect(request).toHaveBeenLastCalledWith("lab", "/public/lab/inventory/7/watch/", { method: "DELETE" });
  });
  it("reports an eligibility failure without showing a successful subscription", async () => {
    request.mockRejectedValue(new Error("An active membership is required."));
    view();
    fireEvent.click(screen.getByRole("button", { name: "Notify me when back" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("An active membership is required.");
    expect(screen.queryByRole("button", { name: "Cancel notification" })).not.toBeInTheDocument();
  });
});
