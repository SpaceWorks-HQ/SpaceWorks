import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PersonalInbox } from "./PersonalInbox";

const { memberRequest } = vi.hoisted(() => ({ memberRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ memberRequest, staffRequest: vi.fn(), getAccessToken: () => null }));

describe("member inbox", () => {
  it("uses the member API, shows unread state and refreshes after acknowledging a row", async () => {
    let read = false;
    memberRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
      if (options?.method === "POST") { read = true; return {}; }
      if (path.endsWith("/unread-count")) return { count: read ? 0 : 1 };
      return { count: 1, next: null, previous: null, results: [{ id: 1, feature: "bookings", event: "confirmed",
        title: "Your booking", summary: "Confirmed", link: "/m/local/member",
        created_at: "2026-10-11T00:00:00Z", read_at: read ? "2026-10-11T00:01:00Z" : null }] };
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const rendered = render(<QueryClientProvider client={client}><PersonalInbox makerspaceId={7} member /></QueryClientProvider>);
    try {
      fireEvent.click(await screen.findByRole("button", { name: "Mark read" }));
      await waitFor(() => expect(screen.getByText("(0 unread)")).toBeVisible());
      expect(memberRequest).toHaveBeenCalledWith("/notifications/inbox/7/1/read", { method: "POST" });
      expect(screen.queryByRole("button", { name: "Mark read" })).not.toBeInTheDocument();
    } finally { rendered.unmount(); client.clear(); memberRequest.mockReset(); }
  });

  it.each(["//external.test", "/\\external.test", "/\t/external.test", "/\n/external.test", "/\x7fpath"])(
    "does not render a browser-normalized unsafe link %j", async (link) => {
      memberRequest.mockImplementation(async (path: string) => path.endsWith("/unread-count") ? { count: 0 } : {
        count: 1, next: null, previous: null, results: [{ id: 1, feature: "events", event: "published", link,
          title: "Event", summary: "Summary", read_at: "2026-10-11T00:01:00Z", created_at: "2026-10-11T00:00:00Z" }],
      });
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      const rendered = render(<QueryClientProvider client={client}><PersonalInbox makerspaceId={7} member /></QueryClientProvider>);
      try {
        await screen.findByText("Summary");
        expect(screen.queryByRole("link", { name: "Open" })).not.toBeInTheDocument();
      } finally { rendered.unmount(); client.clear(); memberRequest.mockReset(); }
    },
  );
});
