import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  EventSeriesFields,
  emptySeriesForm,
  seriesPayload,
  type SeriesFormValues,
} from "./EventSeriesForm";

function Harness() {
  const [values, setValues] = useState<SeriesFormValues>({
    ...emptySeriesForm,
    recurrence_timezone: "America/New_York",
    dtstart_local_time: "18:00",
  });
  return <EventSeriesFields values={values} setValues={setValues} />;
}

describe("EventSeriesFields", () => {
  it("previews cadence as a local wall-clock schedule", () => {
    render(<Harness />);

    expect(screen.getByText(
      "Every week at 18:00 (America/New_York).",
    )).toBeVisible();
    expect(screen.getByText(
      "Wall-clock time stays fixed across daylight-saving changes.",
    )).toBeVisible();
    fireEvent.change(screen.getByLabelText("Repeats"), { target: { value: "DAILY" } });
    expect(screen.getByText(
      "Every day at 18:00 (America/New_York).",
    )).toBeVisible();
  });

  it("builds a canonical RRULE body without a UTC DTSTART", () => {
    const payload = seriesPayload({
      ...emptySeriesForm,
      title: " Weekly class ",
      location: " Studio ",
      frequency: "WEEKLY",
      interval: 2,
      byday: "mo,we",
    });

    expect(payload.recurrence_rule).toBe("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE");
    expect(payload.recurrence_rule).not.toContain("DTSTART");
    expect(payload.title).toBe("Weekly class");
    expect(payload.location).toBe("Studio");
  });
});
