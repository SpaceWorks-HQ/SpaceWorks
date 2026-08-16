import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";

import { ResetPasswordPage } from "../staff/ResetPasswordPage";

const { publicV1Request } = vi.hoisted(() => ({ publicV1Request: vi.fn() }));

vi.mock("../../lib/api", () => ({ publicV1Request }));

const ACKNOWLEDGEMENT =
  "If an account exists for that email, a password reset request has been accepted.";
const EMAIL = "member@example.test";
const PASSWORD = "New-password-419!";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function renderPage(route = "/reset-password") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ResetPasswordPage />
      <LocationProbe />
    </MemoryRouter>,
  );
}

function fillPassword(prefix = "") {
  fireEvent.change(screen.getByLabelText(`${prefix}New password`), {
    target: { value: PASSWORD },
  });
  fireEvent.change(screen.getByLabelText(`${prefix}Confirm password`), {
    target: { value: PASSWORD },
  });
}

async function reachConfirmation() {
  publicV1Request.mockResolvedValueOnce({ detail: ACKNOWLEDGEMENT });
  renderPage();
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: EMAIL } });
  fireEvent.click(screen.getByRole("button", { name: "Request recovery code" }));
  expect(await screen.findByRole("heading", { name: "Enter your recovery code" })).toBeInTheDocument();
}

describe("password recovery", () => {
  beforeEach(() => publicV1Request.mockReset());

  afterEach(() => vi.useRealTimers());

  it("advances through all three steps while carrying email outside the URL", async () => {
    publicV1Request
      .mockResolvedValueOnce({ detail: ACKNOWLEDGEMENT })
      .mockResolvedValueOnce({ detail: "Password updated." });
    renderPage();

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: EMAIL } });
    fireEvent.click(screen.getByRole("button", { name: "Request recovery code" }));

    expect(await screen.findByText(ACKNOWLEDGEMENT)).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/reset-password");
    expect(screen.getByTestId("location")).not.toHaveTextContent(EMAIL);
    expect(JSON.parse(publicV1Request.mock.calls[0][1].body)).toEqual({ email: EMAIL });

    fireEvent.change(screen.getByLabelText("Six-digit code"), { target: { value: "123456" } });
    fillPassword();
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));

    expect(await screen.findByRole("heading", { name: "Password updated" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to sign in" })).toHaveAttribute("href", "/admin");
    expect(JSON.parse(publicV1Request.mock.calls[1][1].body)).toEqual({
      email: EMAIL,
      code: "123456",
      new_password: PASSWORD,
    });
  });

  it.each([
    ["wrong code", { detail: "Invalid or expired verification code." }],
    ["unknown address", { detail: "An account was not found." }],
    ["password policy", { new_password: ["Choose a stronger password."] }],
  ])("renders the same generic message for a %s rejection", async (_label, rejection) => {
    await reachConfirmation();
    publicV1Request.mockRejectedValueOnce(rejection);
    fireEvent.change(screen.getByLabelText("Six-digit code"), { target: { value: "654321" } });
    fillPassword();
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid or expired verification code.",
    );
  });

  it("replaces the request form with the deployment-level unavailable state", async () => {
    publicV1Request.mockRejectedValueOnce({
      code: "recovery_unavailable",
      detail: "Password recovery is unavailable.",
    });
    const view = renderPage();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: EMAIL } });
    fireEvent.click(screen.getByRole("button", { name: "Request recovery code" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Password recovery is unavailable on this deployment — contact your makerspace staff",
    );
    expect(view.container.querySelector("form")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
  });

  it("keeps legacy query links working with the legacy payload", async () => {
    publicV1Request.mockResolvedValueOnce({ detail: "Password updated." });
    renderPage("/reset-password?uid=user-42&token=legacy-token");

    expect(screen.getByRole("heading", { name: "Set a new password" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    fillPassword();
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));

    await waitFor(() => expect(publicV1Request).toHaveBeenCalledTimes(1));
    expect(JSON.parse(publicV1Request.mock.calls[0][1].body)).toEqual({
      uid: "user-42",
      token: "legacy-token",
      new_password: PASSWORD,
    });
  });

  it("disables resend for the visible cooldown and then re-enables it", async () => {
    vi.useFakeTimers();
    publicV1Request.mockResolvedValueOnce({ detail: ACKNOWLEDGEMENT });
    renderPage();

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: EMAIL } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Request recovery code" }));
    });

    expect(screen.getByRole("button", { name: "Request another code in 60s" })).toBeDisabled();
    act(() => vi.advanceTimersByTime(60_000));
    expect(screen.getByRole("button", { name: "Request another code" })).toBeEnabled();
  });
});
