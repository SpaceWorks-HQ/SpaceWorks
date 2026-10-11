import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { Queues } from "./Queues";
const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", () => ({ staffRequest }));
vi.mock("./QueuesModals", () => ({ AssignIssueModal: () => null, RejectRequestModal: () => null, ReturnDueModal: () => null, ReturnRequestModal: () => null }));
vi.mock("./QueuesAcceptModal", () => ({ AcceptRequestModal: () => null }));
beforeEach(() => { staffRequest.mockReset(); staffRequest.mockResolvedValue({ count: 0, results: [] }); });
it.each([["pending", "Pending review", "pending-requests"], ["accepted", "Ready for handover", "accepted-requests"]])("narrows %s to one queue through URL state", async (queue, heading, endpoint) => {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[`/admin/requests?queue=${queue}`]}><Queues makerspace={{ id: 7 } as never} guestOnly={false} /></MemoryRouter></QueryClientProvider>);
  expect(screen.getByText(heading)).toBeVisible();
  expect(screen.queryByText("Active loans")).not.toBeInTheDocument();
  expect(screen.queryByText("History")).not.toBeInTheDocument();
  const queues = () => staffRequest.mock.calls.filter(([path]) => /\/(pending-requests|accepted-requests|active-loans|request-history)\?/.test(path));
  await waitFor(() => expect(queues()).toHaveLength(1));
  expect(queues()[0][0]).toContain(`/admin/makerspace/7/${endpoint}?`);
});
