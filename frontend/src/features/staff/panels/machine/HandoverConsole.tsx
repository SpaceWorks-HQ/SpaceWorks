import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { MachineServiceRequest } from "../../../../generated/api";
import { staffRequest } from "../../../../lib/api";
import { Panel, useStaffGet } from "../shared";

/**
 * Front-desk handover of finished machine jobs.
 *
 * Deliberately not a slimmed-down MachineServiceConsole. That one is the machine
 * lifecycle -- queues, pools, manual usage, accept/start/complete -- and the whole reason
 * `collect_service_request` exists is that handing a member their finished print should
 * not require any of it. So this asks for one thing (what is waiting) and offers one
 * action (hand it over).
 *
 * The backend narrows a collect-only actor's queryset to completed jobs by itself, so the
 * `status=completed` filter here is what a *manager* sees too rather than a client-side
 * permission check. Nothing on this screen is trusted to enforce anything.
 */

type Props = { makerspaceId: number; enabled: boolean };

const money = (payment: MachineServiceRequest["payment"]) => {
  if (!payment) return null;
  const paid = payment.status === "paid_online" || payment.status === "paid_offline";
  return {
    paid: paid || payment.status === "waived",
    label: payment.status === "waived" ? "Waived" : `${payment.currency.toUpperCase()} ${payment.amount}`.trim(),
    tone: paid || payment.status === "waived" ? "text-muted" : "text-warn-ink",
  };
};

export function HandoverConsole({ makerspaceId, enabled }: Props) {
  const queryClient = useQueryClient();
  const queryKey = ["machine-service-handover", makerspaceId];
  const waiting = useStaffGet<MachineServiceRequest[]>(
    queryKey,
    `/admin/makerspaces/${makerspaceId}/machine-service/requests?status=completed`,
    enabled,
  );

  const collect = useMutation({
    mutationFn: (id: number) =>
      staffRequest(`/admin/machine-service/requests/${id}/collect`, { method: "POST", body: "{}" }),
    // Invalidate rather than filter locally: collecting is the one thing that removes a
    // row from this list, and a refetch also picks up jobs finished since the page loaded.
    onSuccess: () => void queryClient.invalidateQueries({ queryKey }),
  });

  if (!enabled) return null;

  const rows = waiting.data ?? [];

  return (
    <Panel title="Awaiting collection">
      {waiting.isLoading ? <p className="text-sm text-muted">Loading…</p> : null}
      {waiting.isError ? (
        <p className="text-sm text-danger">Could not load finished jobs.</p>
      ) : null}
      {!waiting.isLoading && !waiting.isError && rows.length === 0 ? (
        <p className="text-sm text-muted">Nothing is waiting to be handed over.</p>
      ) : null}

      {rows.length > 0 ? (
        <ul className="divide-y divide-line">
          {rows.map((row) => {
            const payment = money(row.payment);
            return (
              <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{row.title}</p>
                  <p className="truncate text-xs text-muted">
                    {row.requester_name || row.requester?.username || "Unknown requester"}
                    {row.machine?.name ? ` · ${row.machine.name}` : ""}
                    {row.completed_at ? ` · finished ${new Date(row.completed_at).toLocaleString()}` : ""}
                  </p>
                  {payment ? (
                    <p className={`text-xs ${payment.tone}`}>
                      {payment.paid ? "Paid" : "Unpaid"} · {payment.label}
                    </p>
                  ) : null}
                </div>
                <button
                  type="button"
                  className="desk-button-primary"
                  disabled={collect.isPending}
                  onClick={() => collect.mutate(row.id)}
                >
                  Hand over
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}

      {collect.isError ? (
        <p className="mt-3 text-sm text-danger">
          Could not mark that job collected. It may have been handed over already.
        </p>
      ) : null}
    </Panel>
  );
}
