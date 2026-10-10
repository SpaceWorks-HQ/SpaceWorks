import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "../../lib/api";
import { expectNoA11yViolations } from "../../test/axe";
import { MakerspaceProfileSettings } from "./MakerspaceProfileSettings";
import { MakerspacePaymentSettings } from "./MakerspacePaymentSettings";
import type { Makerspace } from "./StaffPanels";
import { emptyWeek, hoursDraft, serializeHours, validateHours, type MakerspaceProfile } from "./makerspaceProfileForm";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), staffRequest,
}));

const profile: MakerspaceProfile = {
  timezone: "UTC", country: "", default_currency: "usd", opening_hours: {},
  timezone_choices: ["UTC", "Asia/Kolkata"], country_choices: ["IN", "US"],
};

function mount(makerspaceId = 7) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidation = vi.spyOn(client, "invalidateQueries");
  return { ...render(<QueryClientProvider client={client}><MakerspaceProfileSettings makerspaceId={makerspaceId} /></QueryClientProvider>), invalidation, client };
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (_path: string, options?: RequestInit) => options?.method === "PATCH"
    ? { ...profile, ...JSON.parse(String(options.body)) } : profile);
});

describe("MakerspaceProfileSettings", () => {
  it("loads and saves country, zone, multiple intervals and a holiday; refreshes related server state", async () => {
    const { container, invalidation } = mount();
    await screen.findByRole("combobox", { name: "Timezone" });
    expect(screen.getByRole("button", { name: "Save location & hours" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Timezone" }), { target: { value: "Asia/Kolkata" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Country" }), { target: { value: "IN" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Set weekly opening hours" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Monday interval" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Monday end 1" }), { target: { value: "12:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Monday interval" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Monday start 2" }), { target: { value: "13:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Add exception" }));
    fireEvent.change(screen.getByLabelText("Exception date 1"), { target: { value: "2026-12-25" } });
    fireEvent.click(screen.getByRole("button", { name: "Save location & hours" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/profile", {
      method: "PATCH", body: JSON.stringify({ opening_hours: {
        weekly: { ...emptyWeek(), mon: [{ start: "09:00", end: "12:00" }, { start: "13:00", end: "17:00" }] },
        exceptions: { "2026-12-25": [] },
      }, timezone: "Asia/Kolkata", country: "IN" }),
    }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved.");
    expect(invalidation).toHaveBeenCalledWith({ queryKey: ["tenant-bootstrap"] });
    expect(invalidation).toHaveBeenCalledWith({ queryKey: ["payment-settings", 7] });
    await expectNoA11yViolations(container);
  });

  it("blocks overlapping intervals before sending a mutation", async () => {
    mount();
    await screen.findByRole("combobox", { name: "Timezone" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Set weekly opening hours" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Monday interval" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Monday interval" }));
    fireEvent.click(screen.getByRole("button", { name: "Save location & hours" }));
    expect(screen.getByRole("alert")).toHaveTextContent("non-overlapping");
    expect(staffRequest).not.toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ method: "PATCH" }));
  });

  it("sends only edited fields so a timezone edit cannot overwrite payment currency or hours", async () => {
    mount();
    await screen.findByRole("combobox", { name: "Timezone" });
    fireEvent.change(screen.getByRole("combobox", { name: "Timezone" }), { target: { value: "Asia/Kolkata" } });
    fireEvent.click(screen.getByRole("button", { name: "Save location & hours" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/profile", {
      method: "PATCH", body: JSON.stringify({ timezone: "Asia/Kolkata" }),
    }));
  });

  it("can close a day and remove an exception without losing other days", async () => {
    staffRequest.mockResolvedValue({ ...profile, opening_hours: { weekly: {
      ...emptyWeek(), mon: [{ start: "09:00", end: "17:00" }], tue: [{ start: "10:00", end: "12:00" }],
    }, exceptions: { "2026-12-25": [] } } });
    mount();
    await screen.findByRole("button", { name: "Remove Monday interval 1" });
    fireEvent.click(screen.getByRole("button", { name: "Remove Monday interval 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove exception 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Save location & hours" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(expect.anything(), {
      method: "PATCH", body: JSON.stringify({ opening_hours: {
        weekly: { ...emptyWeek(), tue: [{ start: "10:00", end: "12:00" }] }, exceptions: {},
      } }),
    }));
  });

  it("shows typed field errors and retains the editable draft", async () => {
    staffRequest.mockImplementation(async (_path: string, options?: RequestInit) => {
      if (options?.method === "PATCH") throw new StructuredApiError(400, { code: "invalid_profile", detail: "Check the profile fields.", fields: { timezone: ["Enter a valid IANA timezone."] } });
      return profile;
    });
    mount();
    await screen.findByRole("combobox", { name: "Timezone" });
    fireEvent.change(screen.getByRole("combobox", { name: "Timezone" }), { target: { value: "Asia/Kolkata" } });
    fireEvent.click(screen.getByRole("button", { name: "Save location & hours" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a valid IANA timezone.");
    expect(screen.getByRole("combobox", { name: "Timezone" })).toHaveValue("Asia/Kolkata");
  });

  it("keeps an old save response in its own tenant cache after switching makerspaces", async () => {
    let finish!: (value: MakerspaceProfile) => void;
    const pending = new Promise<MakerspaceProfile>(resolve => { finish = resolve; });
    staffRequest.mockImplementation(async (path: string, options?: RequestInit) => {
      if (options?.method === "PATCH") return pending;
      return path.includes("/8/") ? { ...profile, country: "US" } : profile;
    });
    const { rerender, client } = mount();
    await screen.findByRole("combobox", { name: "Timezone" });
    fireEvent.change(screen.getByRole("combobox", { name: "Timezone" }), { target: { value: "Asia/Kolkata" } });
    fireEvent.click(screen.getByRole("button", { name: "Save location & hours" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ method: "PATCH" })));
    rerender(<QueryClientProvider client={client}><MakerspaceProfileSettings makerspaceId={8} /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Country" })).toHaveValue("US"));
    finish({ ...profile, timezone: "Asia/Kolkata" });
    await waitFor(() => expect(client.getQueryData<MakerspaceProfile>(["makerspace-profile", 7])?.timezone).toBe("Asia/Kolkata"));
    expect(screen.getByRole("combobox", { name: "Country" })).toHaveValue("US");
    expect(screen.getByRole("combobox", { name: "Timezone" })).toHaveValue("UTC");
  });

  it("refreshes profile currency when payment settings save the shared default", async () => {
    let currency = "usd";
    staffRequest.mockImplementation(async (path: string, options?: RequestInit) => {
      if (options?.method === "PATCH") currency = JSON.parse(String(options.body)).default_currency;
      return path.endsWith("/profile") ? { ...profile, default_currency: currency } : {
        default_currency: currency, effective_mode: "unavailable", connect_status: "unconnected",
        stripe_publishable_key_set: false, stripe_secret_key_set: false, stripe_webhook_secret_set: false,
      };
    });
    const { client, rerender } = mount();
    rerender(<QueryClientProvider client={client}>
      <MakerspaceProfileSettings makerspaceId={7} />
      <MakerspacePaymentSettings makerspace={{ id: 7, enabled_features: [] } as unknown as Makerspace} />
    </QueryClientProvider>);
    await screen.findByRole("textbox", { name: "Default currency" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save payment settings" })).toBeEnabled());
    fireEvent.change(screen.getByRole("textbox", { name: "Default payment currency" }), { target: { value: "eur" } });
    fireEvent.click(screen.getByRole("button", { name: "Save payment settings" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Default currency" })).toHaveValue("eur"));
    expect(screen.getByRole("button", { name: "Save location & hours" })).toBeDisabled();
  });
});

describe("opening-hours draft", () => {
  it("round-trips always-open and explicit closed schedules", () => {
    expect(serializeHours(hoursDraft({}))).toEqual({});
    const closed = { weekly: emptyWeek(), exceptions: {} };
    expect(serializeHours(hoursDraft(closed))).toEqual(closed);
    const exceptionOnly = { weekly: {}, exceptions: { "2026-12-25": [] } };
    expect(serializeHours(hoursDraft(exceptionOnly))).toEqual(exceptionOnly);
  });
  it("rejects duplicate/invalid dates, overnight and malformed times, permits 24:00", () => {
    expect(validateHours({ ...hoursDraft({}), exceptions: [{ date: "2026-02-30", intervals: [] }] })).toContain("valid date");
    expect(validateHours({ ...hoursDraft({}), exceptions: [{ date: "2026-12-25", intervals: [] }, { date: "2026-12-25", intervals: [] }] })).toContain("unique");
    for (const [start, end] of [["22:00", "02:00"], ["9:00", "12:00"], ["24:00", "24:00"]]) {
      expect(validateHours({ configured: true, weekly: { ...emptyWeek(), mon: [{ start, end }] }, exceptions: [] })).not.toBeNull();
    }
    expect(validateHours({ configured: true, weekly: { ...emptyWeek(), mon: [{ start: "00:00", end: "24:00" }] }, exceptions: [] })).toBeNull();
  });
});
