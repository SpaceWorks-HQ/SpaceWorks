import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { JobTray } from "./JobTray";
import { clearJobs, getJobSession, jobStore, trackJob, updateJob } from "./jobStore";
import { expectNoA11yViolations } from "../../test/axe";
const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest: request }));
beforeEach(() => { clearJobs(); request.mockReset(); });
function mount() { const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); return render(<QueryClientProvider client={client}><JobTray makerspaceId={1} /></QueryClientProvider>); }
it("continues observing a job after its source panel unmounts and announces completion", async () => {
  trackJob({ key: "import:1", makerspaceId: 1, label: "Inventory import", endpoint: "/job", status: "running" });
  request.mockResolvedValue({ status: "completed" }); const { container } = mount();
  fireEvent.click(screen.getByText(/Background jobs/));
  await waitFor(() => expect(jobStore.snapshot()[0].status).toBe("completed"));
  expect(screen.getByRole("status")).toHaveTextContent("Inventory import: completed");
  await expectNoA11yViolations(container);
  fireEvent.click(screen.getByRole("button", { name: "Dismiss Inventory import" }));
  expect(screen.queryByText(/Background jobs/)).not.toBeInTheDocument();
});
it("does not query another tenant's jobs and forgets them on account cleanup", () => {
  trackJob({ key: "private", makerspaceId: 2, label: "Other export", endpoint: "/private", status: "pending" }); mount();
  expect(request).not.toHaveBeenCalled(); clearJobs(); expect(jobStore.snapshot()).toEqual([]);
});
it("keeps a failed status read retryable without falsely completing the job", async () => {
  trackJob({ key: "export", makerspaceId: 1, label: "Export", endpoint: "/exports", collectionId: "7", status: "running" });
  request.mockRejectedValueOnce(new Error("Offline")).mockResolvedValue([{ id: "7", status: "available" }]); mount();
  fireEvent.click(screen.getByText(/Background jobs/));
  fireEvent.click(await screen.findByRole("button", { name: "Retry status" }));
  await waitFor(() => expect(jobStore.snapshot()[0].status).toBe("available"));
});

it("discards late creation and progress callbacks from a logged-out session", () => {
  const previous = getJobSession();
  clearJobs();
  const job = { key: "export:7", makerspaceId: 1, label: "Export", endpoint: "/exports", status: "running" };
  trackJob(job, previous);
  expect(jobStore.snapshot()).toEqual([]);
  trackJob(job);
  updateJob(job.key, "available", previous);
  expect(jobStore.snapshot()[0].status).toBe("running");
});
