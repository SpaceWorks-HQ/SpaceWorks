import type { Availability } from "../../types/inventory";

type AvailabilityBadgeProps = {
  availability: Availability;
};

type Tone = "success" | "warn" | "danger" | "neutral";

// Filled status-box styling (theme-token fills plus readable ink labels) so the availability
// pill matches the rest of the status boxes and stays legible in BOTH light and dark
// modes — the old tinted success text washed out in dark "Available".
const TONE_CLASS: Record<Tone, string> = {
  success:
    "border-success bg-success text-on-success dark:bg-success/15 dark:text-success-ink",
  warn: "border-warn bg-warn text-on-warn dark:bg-warn/15 dark:text-warn-ink",
  danger: "border-danger bg-danger text-bg",
  neutral: "border-outline bg-surface text-muted",
};

function toneForAvailability(
  label: NonNullable<Availability>["label"],
): Tone {
  if (label === "Limited") {
    return "warn";
  }

  if (label === "Unavailable") {
    return "danger";
  }

  if (label === "Available") {
    return "success";
  }

  return "neutral";
}

function textForAvailability(availability: NonNullable<Availability>): string {
  const label = availability.label;

  if (availability.mode === "exact_count" && availability.count != null) {
    if (label === "Unavailable") {
      return "Unavailable";
    }

    if (label === "Limited") {
      return `${availability.count} limited`;
    }

    return `${availability.count} available`;
  }

  return label ?? "Available";
}

export function AvailabilityBadge({ availability }: AvailabilityBadgeProps) {
  if (availability === null) {
    return null;
  }

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-xs font-semibold tracking-tight ${TONE_CLASS[toneForAvailability(availability.label)]}`}
    >
      {textForAvailability(availability)}
    </span>
  );
}
