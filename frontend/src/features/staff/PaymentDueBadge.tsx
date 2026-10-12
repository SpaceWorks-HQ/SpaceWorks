import { Badge } from "../../components/ui";

export const DUE_OPTIONS = [["upcoming", "Upcoming"], ["due_today", "Due today"], ["overdue", "Overdue"]] as const;

export function PaymentDueBadge({ payment }: { payment: { due_date?: string | null; due_state?: string } }) {
  if (!payment.due_date) return null;
  const state = DUE_OPTIONS.find(([key]) => key === payment.due_state)?.[1];
  // due_date is already the owning makerspace's day. Browser timezone conversion
  // would shift dates for members travelling or viewing a collaborative event.
  return <Badge tone={payment.due_state === "overdue" ? "danger" : payment.due_state === "due_today" ? "warn" : "neutral"}>
    {state ? `${state} · ` : "Due "}{payment.due_date}
  </Badge>;
}
