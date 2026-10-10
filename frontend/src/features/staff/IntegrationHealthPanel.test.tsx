import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { expectNoA11yViolations } from "../../test/axe";
import { IntegrationHealthPanel } from "./IntegrationHealthPanel";
import type { Makerspace } from "./StaffPanels";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));

const recent = new Date(Date.now() - 5 * 60_000).toISOString();

const health = {
  status: "warn",
  email: { status: "ok", total: 3, pending: 0, sent: 3, failed: 0, stalled: 0, last_failure: null },
  deliveries_by_stream: { status: "ok", hardware: recent, printing: null },
  smtp: { status: "ok", configured: true },
  telegram: { status: "ok", configured: false },
  chat_destinations: {
    status: "warn",
    destinations: [
      {
        id: 1, channel: "slack", label: "Front desk", is_active: true, configured: true,
        last_sent_at: recent, failed: 2,
        last_failure: { error: "notification_delivery_failed:WebhookDeliveryError", at: recent },
      },
      {
        id: 2, channel: "webhook", label: "ERP", is_active: false, configured: true,
        last_sent_at: null, failed: 0, last_failure: null,
      },
      {
        id: 3, channel: "telegram", label: "Workshop", is_active: true, configured: false,
        last_sent_at: null, failed: 0, last_failure: null,
      },
    ],
    legacy_deliveries: {
      discord: { configured: true, last_sent_at: recent, failed: 0, last_failure: null },
    },
  },
  worker: { status: "ok", broker_configured: true, eager: false, last_seen: recent, stale: false },
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <IntegrationHealthPanel makerspace={{ id: 7, slug: "demo", name: "Demo" } as Makerspace} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("IntegrationHealthPanel", () => {
  beforeEach(() => {
    staffRequest.mockReset();
    staffRequest.mockResolvedValue(health);
  });

  it("shows every room with its not-configured, inactive and last-failure state", async () => {
    const { container } = renderPanel();

    expect(await screen.findByText("Chat and webhook rooms")).toBeInTheDocument();
    expect(screen.getByText("Slack - Front desk")).toBeInTheDocument();
    expect(screen.getByText("2 failed")).toBeInTheDocument();
    expect(screen.getByText(/Last delivery failed .*WebhookDeliveryError/)).toBeInTheDocument();
    expect(screen.getByText("Signed webhook - ERP")).toBeInTheDocument();
    expect(screen.getByText("Inactive")).toBeInTheDocument();
    expect(screen.getByText("Telegram - Workshop")).toBeInTheDocument();
    expect(screen.getAllByText("Not configured").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Discord (space-wide)")).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("says so when no room exists", async () => {
    staffRequest.mockResolvedValue({
      ...health,
      chat_destinations: { status: "ok", destinations: [], legacy_deliveries: {} },
    });
    renderPanel();

    expect(await screen.findByText("No chat or webhook rooms are configured.")).toBeInTheDocument();
  });

  it("shows SMS configuration and a scoped native-push failure", async () => {
    staffRequest.mockResolvedValue({
      ...health,
      sms: { status: "ok", configured: false },
      native_push: {
        status: "warn", configured: true, enabled: false, failed: 1,
        last_failure: { error: "notification_delivery_failed:PushProviderError", at: recent },
      },
    });
    const { container } = renderPanel();
    expect(await screen.findByText("SMS")).toBeInTheDocument();
    expect(screen.getByText("Native push")).toBeInTheDocument();
    expect(screen.getByText("Disabled for this makerspace")).toBeInTheDocument();
    expect(screen.getByText(/Last delivery failed:.*PushProviderError/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });
});
