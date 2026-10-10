import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlatformEmailPanel } from "./PlatformEmailPanel";
import { PlatformSocialAuthPanel } from "./PlatformSocialAuthPanel";
import { PlatformStripeConnectPanel } from "./PlatformStripeConnectPanel";

const { query } = vi.hoisted(() => ({ query: vi.fn() }));
vi.mock("./StaffPanels", async () => {
  const actual = await vi.importActual<typeof import("./StaffPanels")>("./StaffPanels");
  return { ...actual, useStaffGet: query };
});

function wrap(element: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{element}</QueryClientProvider>);
}

describe("platform configuration states", () => {
  it("shows an unconfigured SMTP host explicitly", () => {
    query.mockReturnValue({ data: {
      smtp_host: "", smtp_port: 587, smtp_username: "", smtp_use_tls: true,
      smtp_use_ssl: false, from_email: "", smtp_password_set: false,
    }, isLoading: false });
    wrap(<PlatformEmailPanel />);
    expect(screen.getByText("Not configured")).toBeInTheDocument();
  });

  it("shows both dormant social providers", () => {
    query.mockReturnValue({ data: {
      google_web_client_id: "", google_ios_client_id: "", google_android_client_id: "",
      apple_service_id: "", apple_native_app_ids: [], apple_team_id: "", apple_key_id: "",
      apple_private_key_set: false,
    }, isLoading: false });
    wrap(<PlatformSocialAuthPanel />);
    expect(screen.getByText("Google: Not configured")).toBeInTheDocument();
    expect(screen.getByText("Apple: Not configured")).toBeInTheDocument();
  });

  it("does not label a partial Connect configuration as configured", () => {
    query.mockReturnValue({ data: {
      stripe_secret_key_set: true, stripe_connect_client_id: "", application_fee_bps: 0,
    }, isLoading: false });
    wrap(<PlatformStripeConnectPanel />);
    expect(screen.getByText("Not configured")).toBeInTheDocument();
  });
});
