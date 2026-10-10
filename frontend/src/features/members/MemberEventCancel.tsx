import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";

export function MemberEventCancel({ makerspaceId, makerspaceSlug, registrationId, status, canCancel = true, cutoffAt }: {
  makerspaceId: number; makerspaceSlug: string; registrationId: number; status: string;
  canCancel?: boolean; cutoffAt?: string;
}) {
  const queryClient = useQueryClient();
  const cancel = useMutation({
    mutationFn: () => staffRequest<{ status: "cancelled" }>(
      `/member/makerspaces/${makerspaceId}/event-registrations/${registrationId}/cancel/`,
      { method: "POST", body: JSON.stringify({}) },
    ),
    onSuccess: async () => { await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["member", makerspaceSlug, "activity"] }),
      queryClient.invalidateQueries({ queryKey: ["public-events", makerspaceSlug] }),
      queryClient.invalidateQueries({ queryKey: ["member", makerspaceSlug, "partner-events"] }),
      queryClient.invalidateQueries({ queryKey: ["member", makerspaceSlug, "payments"] }),
    ]); },
  });
  if (!["pending_approval", "registered", "waitlisted"].includes(status)) return null;
  if (!canCancel) return <p className="mt-1 text-sm text-muted">The cancellation deadline has passed. Contact staff.</p>;
  return <div className="mt-1">
    {cutoffAt ? <p className="text-xs text-muted">Cancel before {new Date(cutoffAt).toLocaleString()}.</p> : null}
    <button className="desk-button-danger" type="button" disabled={cancel.isPending || cancel.isSuccess} onClick={() => cancel.mutate()}>
      {cancel.isPending ? "Cancelling..." : cancel.isSuccess ? "Registration cancelled" : "Cancel registration"}
    </button>
    {cancel.error ? <p className="mt-1 text-sm text-danger" role="alert">{cancel.error.message}</p> : null}
  </div>;
}
