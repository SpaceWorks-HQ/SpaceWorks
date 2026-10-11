/** Calendar days belong to the makerspace, independently of the visitor's zone. */
export function calendarDate(value: Date, timeZone = "UTC") {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(value);
  const part = (type: string) => parts.find((entry) => entry.type === type)!.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function currentMonth(timeZone = "UTC") {
  return calendarDate(new Date(), timeZone).slice(0, 7);
}

// Resolve wall midnight to an instant using the zone's actual offset on that day,
// including DST. A midnight skipped by a transition resolves to the first hour.
export function dayStart(year: number, month: number, day: number, timeZone = "UTC") {
  const wall = Date.UTC(year, month - 1, day);
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  });
  let instant = wall;
  let previous = NaN;
  for (let attempt = 0; attempt < 4; attempt++) {
    const parts = formatter.formatToParts(new Date(instant));
    const part = (type: string) => Number(parts.find((entry) => entry.type === type)!.value);
    const represented = Date.UTC(part("year"), part("month") - 1, part("day"), part("hour"), part("minute"), part("second"));
    const next = instant + wall - represented;
    if (next === instant) break;
    if (next === previous) { instant = Math.max(instant, next); break; }
    previous = instant;
    instant = next;
  }
  return new Date(instant);
}

export function monthWindow(month: string, timeZone = "UTC") {
  const [year, number] = month.split("-").map(Number);
  return { start: dayStart(year, number, 1, timeZone), end: dayStart(year, number + 1, 1, timeZone) };
}
