import { useMutation, useQueryClient } from "@tanstack/react-query";

import { memberRequest } from "../../lib/api";

export function MemberLoanRenew({ makerspaceId, makerspaceSlug, requestId }: {
  makerspaceId: number; makerspaceSlug: string; requestId: number;
}) {
  const client = useQueryClient();
  const renew = useMutation({
    mutationFn: () => memberRequest<{ return_due_at: string; renewal_count: number }>(
      `/member/makerspaces/${makerspaceId}/loans/${requestId}/renew`,
      { method: "POST", body: JSON.stringify({}) },
    ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["member", makerspaceSlug, "activity"] }),
  });
  return <div className="mt-1">
    <button type="button" className="desk-button" disabled={renew.isPending || renew.isSuccess} onClick={() => renew.mutate()}>
      {renew.isPending ? "Renewing..." : renew.isSuccess ? "Loan renewed" : "Renew loan"}
    </button>
    {renew.error ? <p role="alert" className="text-sm text-danger">{renew.error.message}</p> : null}
  </div>;
}
