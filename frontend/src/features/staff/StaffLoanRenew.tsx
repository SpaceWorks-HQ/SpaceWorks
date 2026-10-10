import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";

export function StaffLoanRenew({ makerspaceId, requestId }: { makerspaceId: number; requestId: number }) {
  const client = useQueryClient();
  const renew = useMutation({
    mutationFn: () => staffRequest(`/admin/makerspace/${makerspaceId}/loans/${requestId}/renew`, {
      method: "POST", body: JSON.stringify({}),
    }),
    onSuccess: () => Promise.all([
      client.invalidateQueries({ queryKey: ["active", makerspaceId] }),
      client.invalidateQueries({ queryKey: ["direct-loans", makerspaceId] }),
      client.invalidateQueries({ queryKey: ["request-timeline", requestId] }),
    ]),
  });
  return <span>
    <button className="desk-button" type="button" disabled={renew.isPending} onClick={() => renew.mutate()}>
      {renew.isPending ? "Renewing..." : "Renew loan"}
    </button>
    {renew.error ? <span className="block text-xs text-danger" role="alert">{renew.error.message}</span> : null}
  </span>;
}
