import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useUnreadNotifications } from "../useUnreadNotifications";
import { NotificationInbox } from "./NotificationInbox";
import type { Makerspace } from "./shared";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", () => ({ staffRequest, getAccessToken: () => null }));

const makerspace = { id: 7, name: "Forge" } as Makerspace;
const notification = {
  id: 12, feature: "hardware_requests", event: "submitted", title: "New request", summary: "",
  link: "", read_at: null, created_at: "2026-10-10T00:00:00Z",
};

function Badge({ id }: { id: number }) {
  const count = useUnreadNotifications(id, true);
  return <output aria-label={`Unread ${id}`}>{count}</output>;
}

beforeEach(() => { staffRequest.mockReset(); });

describe("NotificationInbox unread badge", () => {
  it.each(["Mark read", "Mark all read"])("refreshes immediately after %s", async (button) => {
    let unread = 1;
    staffRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
      if (options?.method === "POST") {
        unread = 0;
        return path.endsWith("read-all") ? { updated: 1 } : { ...notification, read_at: "now" };
      }
      if (path.endsWith("unread-count")) return { count: path.includes("/8/") ? 3 : unread };
      return { count: 1, next: null, previous: null, results: [{ ...notification, read_at: unread ? null : "now" }] };
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { unmount } = render(
      <QueryClientProvider client={client}>
        <Badge id={7} /><Badge id={8} />
        <NotificationInbox makerspace={makerspace} />
      </QueryClientProvider>,
    );
    try {
      await waitFor(() => expect(screen.getByLabelText("Unread 7")).toHaveTextContent("1"));
      await waitFor(() => expect(screen.getByLabelText("Unread 8")).toHaveTextContent("3"));
      fireEvent.click(await screen.findByRole("button", { name: button }));
      await waitFor(() => expect(screen.getByLabelText("Unread 7")).toHaveTextContent("0"));
      expect(staffRequest.mock.calls.filter(([path]) => path === "/notifications/inbox/7/unread-count")).toHaveLength(2);
      expect(staffRequest.mock.calls.filter(([path]) => path === "/notifications/inbox/8/unread-count")).toHaveLength(1);
      expect(screen.getByLabelText("Unread 8")).toHaveTextContent("3");
    } finally {
      unmount();
      client.clear();
    }
  });
});
