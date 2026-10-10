export const weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export const dayLabels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export type Interval = { start: string; end: string };
export type WeeklyHours = Record<(typeof weekdays)[number], Interval[]>;
export type OpeningHours = { weekly: WeeklyHours | Record<string, never>; exceptions: Record<string, Interval[]> } | Record<string, never>;
export type HoursDraft = { configured: boolean; weekly: WeeklyHours; exceptions: { date: string; intervals: Interval[] }[] };
export type MakerspaceProfile = {
  timezone: string; country: string; default_currency: string; opening_hours: OpeningHours;
  timezone_choices: string[]; country_choices: string[];
};

export function emptyWeek(): WeeklyHours {
  return { mon: [], tue: [], wed: [], thu: [], fri: [], sat: [], sun: [] };
}

export function hoursDraft(hours: OpeningHours): HoursDraft {
  return {
    configured: Object.keys(hours.weekly ?? {}).length > 0,
    weekly: { ...emptyWeek(), ...hours.weekly },
    exceptions: Object.entries(hours.exceptions ?? {}).map(([date, intervals]) => ({ date, intervals })),
  };
}

export function serializeHours(draft: HoursDraft): OpeningHours {
  if (!draft.configured && draft.exceptions.length === 0) return {};
  return {
    weekly: draft.configured ? draft.weekly : {},
    exceptions: Object.fromEntries(draft.exceptions.map(row => [row.date, row.intervals])),
  };
}

export function validateHours(draft: HoursDraft): string | null {
  const dates = new Set<string>();
  if (draft.exceptions.length > 366) return "Use at most 366 dated exceptions.";
  for (const row of draft.exceptions) {
    const parsed = new Date(`${row.date}T00:00:00Z`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(row.date) || row.date === "9999-12-31" || row.date.startsWith("0000-") || !Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== row.date) {
      return "Enter a valid date for each exception.";
    }
    if (dates.has(row.date)) return "Each exception date must be unique.";
    dates.add(row.date);
  }
  const days = [...(draft.configured ? Object.values(draft.weekly) : []), ...draft.exceptions.map(row => row.intervals)];
  for (const intervals of days) {
    let previousEnd = "";
    if (intervals.length > 24) return "Use at most 24 intervals per day.";
    for (const { start, end } of intervals) {
      const valid = (value: string) => /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value);
      if (!valid(start) || (!valid(end) && end !== "24:00")) return "Use HH:MM; 24:00 is allowed only as an end.";
      if (start >= end || start < previousEnd) return "Intervals must be sorted, non-overlapping and end after start. Split overnight hours across days.";
      previousEnd = end;
    }
  }
  return null;
}
