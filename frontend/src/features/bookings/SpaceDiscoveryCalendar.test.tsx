import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceDiscoveryCalendar } from "./SpaceDiscoveryCalendar";
import { usePublicAvailability, type PublicBookableSpace } from "./publicBookingsApi";
import * as dates from "../discovery/useDiscoveryState";

vi.mock("./publicBookingsApi", () => ({ usePublicAvailability: vi.fn() }));
const space = { public_token: "bench", name: "Bench", show_public_availability: true, show_public_booker_names: false } as PublicBookableSpace;
const interval = { starts_at: "2026-10-16T10:00:00", ends_at: "2026-10-16T12:00:00", booker_name: null };
beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-01T00:00:00Z"));
  vi.mocked(usePublicAvailability).mockReset();
  vi.mocked(usePublicAvailability).mockReturnValue({ data: { availability: [interval] }, isLoading: false, error: null } as ReturnType<typeof usePublicAvailability>);
});
afterEach(() => { vi.restoreAllMocks(); });

it("splits a real tenant daylight-saving fallback month into bounded windows and deduplicates bookings", () => {
  render(<SpaceDiscoveryCalendar slug="lab" space={space} month="2026-10" timeZone="Europe/London" />);
  const calls = vi.mocked(usePublicAvailability).mock.calls;
  expect(calls).toHaveLength(2);
  expect(calls.every(([, , start, end, enabled]) => enabled && Date.parse(end) - Date.parse(start) <= 31 * 86400000)).toBe(true);
  expect(calls[0][3]).toBe(calls[1][2]);
  expect(calls[0][2]).toBe("2026-09-30T23:00:00.000Z");
  expect(calls[1][3]).toBe("2026-11-01T00:00:00.000Z");
  expect(screen.getAllByText(/Booked/)).toHaveLength(1);
});

it("does not display partial availability when the second bounded window failed", () => {
  vi.spyOn(dates, "monthWindow").mockReturnValue({ start: new Date("2026-10-01T00:00:00Z"), end: new Date("2026-11-01T01:00:00Z") });
  vi.mocked(usePublicAvailability).mockReturnValueOnce({ data: { availability: [interval] } } as ReturnType<typeof usePublicAvailability>)
    .mockReturnValueOnce({ error: new Error("Unavailable") } as ReturnType<typeof usePublicAvailability>);
  render(<SpaceDiscoveryCalendar slug="lab" space={space} month="2026-10" />);
  expect(screen.getByRole("alert")).toHaveTextContent("This does not mean the space is free.");
  expect(screen.queryByRole("table")).toBeNull();
});

it("does not fetch an entirely past window", () => {
  render(<SpaceDiscoveryCalendar slug="lab" space={space} month="2026-08" />);
  expect(screen.getByText(/Choose the current month/)).toBeVisible();
  expect(vi.mocked(usePublicAvailability).mock.calls.every((args) => args[4] === false)).toBe(true);
});
