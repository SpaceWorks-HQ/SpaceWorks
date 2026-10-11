import { render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { currentMonth, dayStart, monthWindow } from "./calendarDates";
import { MonthCalendar } from "./MonthCalendar";

afterEach(() => vi.useRealTimers());

it("resolves tenant month boundaries independently of the device timezone", () => {
  const { start, end } = monthWindow("2026-11", "Asia/Kolkata");
  expect(start.toISOString()).toBe("2026-10-31T18:30:00.000Z");
  expect(end.toISOString()).toBe("2026-11-30T18:30:00.000Z");
  expect(monthWindow("2026-12", "Asia/Kolkata").end.toISOString()).toBe("2026-12-31T18:30:00.000Z");
});

it("uses real DST offsets, including a skipped midnight", () => {
  const { start, end } = monthWindow("2026-10", "Europe/London");
  expect(start.toISOString()).toBe("2026-09-30T23:00:00.000Z");
  expect(end.toISOString()).toBe("2026-11-01T00:00:00.000Z");
  expect(end.getTime() - start.getTime()).toBe(31 * 86400000 + 3600000);
  expect(dayStart(2026, 3, 8, "America/Havana").toISOString()).toBe("2026-03-08T05:00:00.000Z");
});

it("chooses the tenant's current month at a UTC month boundary", () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-31T20:00:00Z"));
  expect(currentMonth("Asia/Kolkata")).toBe("2026-11");
  expect(currentMonth("America/New_York")).toBe("2026-10");
});

it("places a UTC October interval on the makerspace's November first", () => {
  render(<MonthCalendar month="2026-11" timeZone="Asia/Kolkata" label="Lab events" entries={[
    { id: "edge", startsAt: "2026-10-31T20:00:00Z", endsAt: "2026-10-31T21:00:00Z", label: "First-day workshop" },
  ]} />);
  expect(screen.getByRole("table")).toHaveAccessibleName(/Asia\/Kolkata/);
  const cell = screen.getByText("First-day workshop").closest("td")!;
  expect(within(cell).getByLabelText(/(?:1 November|November 1).*2026/)).toHaveTextContent("1");
});
