import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SocialSignInButtons } from "./SocialSignInButtons";

const { beginOidcBrowser, completeOidcBrowserCallback, mountGoogleButton, publicV1Request } = vi.hoisted(() => ({
  beginOidcBrowser: vi.fn(),
  completeOidcBrowserCallback: vi.fn(),
  mountGoogleButton: vi.fn(),
  publicV1Request: vi.fn(),
}));

vi.mock("../../lib/api", () => ({ publicV1Request }));
vi.mock("./socialSdk", async () => {
  const actual = await vi.importActual<typeof import("./socialSdk")>("./socialSdk");
  return { ...actual, beginOidcBrowser, completeOidcBrowserCallback, mountGoogleButton };
});

describe("SocialSignInButtons", () => {
  beforeEach(() => {
    mountGoogleButton.mockReset();
    beginOidcBrowser.mockReset();
    completeOidcBrowserCallback.mockReset();
    completeOidcBrowserCallback.mockResolvedValue(null);
    publicV1Request.mockReset();
  });

  it("stays absent when the public config omits social auth", async () => {
    publicV1Request.mockResolvedValue({ email_enabled: false });
    const { container } = render(
      <SocialSignInButtons surface="member" onSuccess={vi.fn()} />,
    );

    await waitFor(() => expect(publicV1Request).toHaveBeenCalledWith("/config"));
    expect(container).toBeEmptyDOMElement();
    expect(mountGoogleButton).not.toHaveBeenCalled();
  });

  it("mounts Google only with the frontend-safe configured client ID", async () => {
    publicV1Request.mockResolvedValue({
      social_auth: {
        google: { enabled: true, web_client_id: "google-web-client" },
      },
    });
    mountGoogleButton.mockResolvedValue(undefined);

    render(<SocialSignInButtons surface="staff" onSuccess={vi.fn()} />);

    expect(await screen.findByLabelText("Social sign in")).toBeInTheDocument();
    await waitFor(() =>
      expect(mountGoogleButton).toHaveBeenCalledWith(
        expect.any(HTMLElement),
        "google-web-client",
        "staff",
        expect.any(Function),
        expect.any(Function),
      ),
    );
  });

  it("drops the member surface when the deployment runs no member accounts", async () => {
    // The staff login screen reads the same endpoint and keeps its providers: staff
    // sign-in is core RBAC and is never gated. Only the member surface 404s behind it.
    publicV1Request.mockResolvedValue({
      social_auth: { google: { enabled: true, web_client_id: "google-web-client" } },
      member_accounts: { enabled: false },
    });
    mountGoogleButton.mockResolvedValue(undefined);

    const { container } = render(
      <SocialSignInButtons surface="member" onSuccess={vi.fn()} />,
    );

    await waitFor(() => expect(publicV1Request).toHaveBeenCalledWith("/config"));
    expect(container).toBeEmptyDOMElement();
    expect(mountGoogleButton).not.toHaveBeenCalled();

    render(<SocialSignInButtons surface="staff" onSuccess={vi.fn()} />);
    expect(await screen.findByLabelText("Social sign in")).toBeInTheDocument();
  });

  it("keeps only configured institution OIDC on an accounts-off member surface", async () => {
    publicV1Request.mockResolvedValue({
      social_auth: {
        google: { enabled: true, web_client_id: "google-web-client" },
        "oidc:campus": {
          enabled: true,
          display_name: "Campus SSO",
          client_id: "campus-client",
          issuer: "https://idp.example.test",
        },
      },
      member_accounts: { enabled: false },
    });
    beginOidcBrowser.mockResolvedValue(undefined);

    render(
      <SocialSignInButtons
        surface="member"
        email="member@example.test"
        makerspaceSlug="main-space"
        onSuccess={vi.fn()}
      />,
    );

    const button = await screen.findByRole("button", { name: "Continue with Campus SSO" });
    expect(mountGoogleButton).not.toHaveBeenCalled();
    fireEvent.click(button);
    await waitFor(() =>
      expect(beginOidcBrowser).toHaveBeenCalledWith(
        "campus",
        "member@example.test",
        "main-space",
      ),
    );
  });
});
