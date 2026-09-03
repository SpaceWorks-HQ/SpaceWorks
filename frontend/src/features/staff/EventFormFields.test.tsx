import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  EventFields,
  emptyEventForm,
  payloadFor,
  type EventFormValues,
} from "./EventFormFields";

function Harness({ approvalLocked = false }: { approvalLocked?: boolean }) {
  const [values, setValues] = useState<EventFormValues>({
    ...emptyEventForm,
    title: "Workshop",
    starts_at: "2026-09-03T10:00",
    ends_at: "2026-09-03T12:00",
  });
  return <EventFields values={values} setValues={setValues} approvalLocked={approvalLocked} />;
}

describe("EventFields registration policy", () => {
  it("keeps the two cutoff modes mutually exclusive", () => {
    render(<Harness />);
    const mode = screen.getByLabelText("Registration cutoff");

    fireEvent.change(mode, { target: { value: "lead" } });
    expect(screen.getByLabelText("Minutes before start")).toBeTruthy();
    expect(screen.queryByLabelText("Cutoff time")).toBeNull();

    fireEvent.change(mode, { target: { value: "absolute" } });
    expect(screen.getByLabelText("Cutoff time")).toBeTruthy();
    expect(screen.queryByLabelText("Minutes before start")).toBeNull();
  });

  it("locks approval after draft and serializes only the selected cutoff", () => {
    render(<Harness approvalLocked />);
    expect(screen.getByLabelText("Require staff approval for registrations")).toBeDisabled();

    const payload = payloadFor({
      ...emptyEventForm,
      title: "Workshop",
      starts_at: "2026-09-03T10:00",
      ends_at: "2026-09-03T12:00",
      registration_cutoff_lead_minutes: 30,
    });
    expect(payload.registration_cutoff_at).toBeNull();
    expect(payload.registration_cutoff_lead_minutes).toBe(30);
  });
});
