import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { StructuredApiError, staffRequest } from "../../lib/api";
import { useStaffGet } from "./StaffPanels";
import type { Makerspace } from "./panels/shared";

type SpaceRules = {
  id: number;
  name: string;
  is_active: boolean;
  approval_mode: "instant" | "approve";
  min_booking_duration_minutes: number;
  max_booking_duration_minutes: number;
  booking_lead_time_minutes: number;
  max_booking_advance_days: number;
  buffer_before_minutes: number;
  buffer_after_minutes: number;
  cancellation_cutoff_hours: number;
};

type RuleField =
  | "min_booking_duration_minutes"
  | "max_booking_duration_minutes"
  | "booking_lead_time_minutes"
  | "max_booking_advance_days"
  | "buffer_before_minutes"
  | "buffer_after_minutes"
  | "cancellation_cutoff_hours"
  | "approval_mode";
type NumberRuleField = Exclude<RuleField, "approval_mode">;
type RuleDraft = Record<NumberRuleField, string> & {
  approval_mode: SpaceRules["approval_mode"];
};
type FieldErrors = Partial<Record<RuleField, string>>;

const NUMBER_FIELDS: Array<{ key: NumberRuleField; label: string; min: number }> = [
  { key: "min_booking_duration_minutes", label: "Minimum booking duration (minutes)", min: 1 },
  { key: "max_booking_duration_minutes", label: "Maximum booking duration (minutes)", min: 1 },
  { key: "booking_lead_time_minutes", label: "Booking lead time (minutes)", min: 0 },
  { key: "max_booking_advance_days", label: "Maximum booking advance (days)", min: 1 },
  { key: "buffer_before_minutes", label: "Buffer before (minutes)", min: 0 },
  { key: "buffer_after_minutes", label: "Cleanup after (minutes)", min: 0 },
  { key: "cancellation_cutoff_hours", label: "Cancellation cutoff (hours before start)", min: 0 },
];
const RULE_FIELDS: RuleField[] = [...NUMBER_FIELDS.map(({ key }) => key), "approval_mode"];

export function MakerspaceBookingRulesSettings({ makerspace }: { makerspace: Makerspace }) {
  // page_size=200 is the backend max; a makerspace never has that many
  // bookable spaces, so one page always covers the whole editable set.
  const spaces = useStaffGet<{ count: number; results: SpaceRules[] }>(
    ["booking-rule-spaces", makerspace.id],
    `/admin/makerspaces/${makerspace.id}/spaces/?page_size=200`,
  );
  const activeSpaces = spaces.data?.results.filter((space) => space.is_active) ?? [];

  return (
    <div className="min-w-0 rounded-md border border-line bg-bg p-4">
      <h3 className="text-base font-semibold text-ink">Booking rules per space</h3>
      <p className="mt-1 text-xs text-muted">Buffers reserve time around each booking. A cancellation cutoff of 0 allows members to cancel any time before the booking starts.</p>
      {spaces.isLoading ? <p className="mt-3 text-sm text-muted">Loading bookable spaces...</p> : null}
      {!spaces.isLoading && activeSpaces.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No active bookable spaces.</p>
      ) : null}
      {activeSpaces.length > 0 ? (
        <div className="mt-4 grid min-w-0 gap-4">
          {activeSpaces.map((space) => (
            <SpaceRuleRow key={space.id} makerspaceId={makerspace.id} space={space} />
          ))}
        </div>
      ) : null}
      {spaces.error ? <p className="mt-3 text-sm text-danger">{spaces.error.message}</p> : null}
    </div>
  );
}

function SpaceRuleRow({ makerspaceId, space }: { makerspaceId: number; space: SpaceRules }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<RuleDraft>(() => draftFromSpace(space));
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [rowError, setRowError] = useState("");

  useEffect(() => {
    setDraft(draftFromSpace(space));
    setFieldErrors({});
    setRowError("");
  }, [
    space.id,
    space.min_booking_duration_minutes,
    space.max_booking_duration_minutes,
    space.booking_lead_time_minutes,
    space.max_booking_advance_days,
    space.buffer_before_minutes,
    space.buffer_after_minutes,
    space.cancellation_cutoff_hours,
    space.approval_mode,
  ]);

  const updateRules = useMutation({
    mutationFn: () =>
      staffRequest<SpaceRules>(`/admin/spaces/${space.id}/booking-rules/`, {
        method: "PATCH",
        body: JSON.stringify({
          min_booking_duration_minutes: Number(draft.min_booking_duration_minutes),
          max_booking_duration_minutes: Number(draft.max_booking_duration_minutes),
          booking_lead_time_minutes: Number(draft.booking_lead_time_minutes),
          max_booking_advance_days: Number(draft.max_booking_advance_days),
          buffer_before_minutes: Number(draft.buffer_before_minutes),
          buffer_after_minutes: Number(draft.buffer_after_minutes),
          cancellation_cutoff_hours: Number(draft.cancellation_cutoff_hours),
          approval_mode: draft.approval_mode,
        }),
      }),
    onMutate: () => {
      setFieldErrors({});
      setRowError("");
    },
    onError: (error) => {
      const parsed = parseRuleErrors(error);
      setFieldErrors(parsed.fieldErrors);
      setRowError(parsed.rowError);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["booking-rule-spaces", makerspaceId] });
    },
  });

  return (
    <form
      className="grid min-w-0 gap-3 rounded-md border border-line p-4"
      onSubmit={(event) => {
        event.preventDefault();
        updateRules.mutate();
      }}
    >
      <h4 className="text-sm font-semibold text-ink">{space.name}</h4>
      <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {NUMBER_FIELDS.map(({ key, label, min }) => (
          <label className="grid min-w-0 content-start gap-1 text-sm text-ink" key={key}>
            <span className="font-semibold">{label}</span>
            <input
              aria-label={`${label} for ${space.name}`}
              className="desk-input"
              type="number"
              min={min}
              value={draft[key]}
              disabled={updateRules.isPending}
              onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))}
            />
            {fieldErrors[key] ? <span className="text-xs text-danger">{fieldErrors[key]}</span> : null}
          </label>
        ))}
        <label className="grid min-w-0 content-start gap-1 text-sm text-ink">
          <span className="font-semibold">Approval mode</span>
          <select
            aria-label={`Approval mode for ${space.name}`}
            className="desk-input"
            value={draft.approval_mode}
            disabled={updateRules.isPending}
            onChange={(event) => setDraft((current) => ({
              ...current,
              approval_mode: event.target.value as SpaceRules["approval_mode"],
            }))}
          >
            <option value="instant">Instant confirmation</option>
            <option value="approve">Staff approval required</option>
          </select>
          {fieldErrors.approval_mode ? (
            <span className="text-xs text-danger">{fieldErrors.approval_mode}</span>
          ) : null}
        </label>
      </div>
      <div>
        <button
          className="desk-button-primary w-full max-w-full sm:w-auto"
          type="submit"
          disabled={updateRules.isPending}
        >
          {updateRules.isPending ? "Saving..." : "Save rules"}
        </button>
      </div>
      {rowError ? <p className="text-sm text-danger">{rowError}</p> : null}
    </form>
  );
}

function draftFromSpace(space: SpaceRules): RuleDraft {
  return {
    min_booking_duration_minutes: String(space.min_booking_duration_minutes),
    max_booking_duration_minutes: String(space.max_booking_duration_minutes),
    booking_lead_time_minutes: String(space.booking_lead_time_minutes),
    max_booking_advance_days: String(space.max_booking_advance_days),
    buffer_before_minutes: String(space.buffer_before_minutes),
    buffer_after_minutes: String(space.buffer_after_minutes),
    cancellation_cutoff_hours: String(space.cancellation_cutoff_hours),
    approval_mode: space.approval_mode,
  };
}

function parseRuleErrors(error: unknown): { fieldErrors: FieldErrors; rowError: string } {
  if (!(error instanceof StructuredApiError) || error.status !== 400) {
    return {
      fieldErrors: {},
      rowError: error instanceof Error ? error.message : "Unable to save booking rules.",
    };
  }

  const fieldErrors: FieldErrors = {};
  RULE_FIELDS.forEach((field) => {
    const message = errorMessage(error.body[field]);
    if (message) fieldErrors[field] = message;
  });
  const rowError = [errorMessage(error.body.detail), errorMessage(error.body.non_field_errors)]
    .filter(Boolean)
    .join(" ");

  return {
    fieldErrors,
    rowError: rowError || (Object.keys(fieldErrors).length === 0 ? error.message : ""),
  };
}

function errorMessage(value: unknown) {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.filter((item) => typeof item === "string").join(" ");
  return "";
}
