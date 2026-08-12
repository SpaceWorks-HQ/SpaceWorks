import type { PropsWithChildren } from "react";

// `accent` and `secondary` exist so a caller that wants to distribute the palette across a
// repeating set (categories, machine types, sections) has all four pastels available here
// rather than hand-rolling a span with its own colour string. Every fill pairs with its FIXED
// `on-*` ink, so none of them inverts in dark mode.
type BadgeTone = "success" | "warn" | "danger" | "accent" | "secondary" | "neutral";

type BadgeProps = PropsWithChildren<{
  tone: BadgeTone;
}>;

const toneClasses: Record<BadgeTone, string> = {
  success: "border-success bg-success text-on-success",
  warn: "border-warn bg-warn text-on-warn",
  danger: "border-danger bg-danger text-bg",
  accent: "border-accent bg-accent text-on-accent",
  secondary: "border-secondary bg-secondary text-on-secondary",
  neutral: "border-outline bg-surface text-muted",
};

export function Badge({ tone, children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-xs font-medium tracking-tight ${toneClasses[tone]}`}
    >
      {children}
    </span>
  );
}
