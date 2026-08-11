import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import type { ArchivedPaymentSummary } from "../../generated/api";
import { StructuredApiError, staffRequest } from "../../lib/api";
import { MemberAuthPanel } from "./MemberAuthPanel";
import { MemberPaymentRows, type MemberPayment } from "./MemberPayments";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Unable to load archived payments.";
}

function ArchivedMakerspacePayments({ summary }: { summary: ArchivedPaymentSummary }) {
  const queryClient = useQueryClient();
  const payments = useQuery({
    queryKey: ["member", "archived-payments", summary.makerspace.id, "payments"],
    queryFn: () => staffRequest<MemberPayment[]>(
      `/member/makerspaces/${summary.makerspace.id}/payments`,
    ),
    retry: false,
  });
  const checkout = useMutation({
    mutationFn: (paymentId: number) => staffRequest<{ checkout_url: string }>(
      `/member/makerspaces/${summary.makerspace.id}/payments/${paymentId}/checkout`,
      { method: "POST" },
    ),
    onSuccess: ({ checkout_url }) => {
      void queryClient.invalidateQueries({
        queryKey: ["member", "archived-payments", summary.makerspace.id, "payments"],
      });
      window.location.assign(checkout_url);
    },
  });

  return (
    <section className="desk-panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-ink">{summary.makerspace.name}</h2>
          <p className="mt-1 text-sm text-muted">
            This makerspace is closed. Outstanding charges can still be settled and receipts remain readable here.
          </p>
        </div>
        <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-muted">
          {summary.pending_count} pending · {summary.total_count} total
        </span>
      </div>
      {payments.isLoading ? (
        <p className="mt-4 text-sm text-muted">Loading payment history…</p>
      ) : null}
      {payments.isError ? (
        <p className="mt-4 text-sm text-danger" role="alert">
          {errorMessage(payments.error)}
        </p>
      ) : null}
      {payments.data ? (
        <MemberPaymentRows
          payments={payments.data}
          checkoutPaymentId={checkout.isPending ? checkout.variables : undefined}
          onCheckout={(paymentId) => checkout.mutate(paymentId)}
        />
      ) : null}
      {checkout.isError ? (
        <p className="mt-3 text-sm text-danger" role="alert">
          {errorMessage(checkout.error)}
        </p>
      ) : null}
    </section>
  );
}

export function ArchivedPayments() {
  const queryClient = useQueryClient();
  const discovery = useQuery({
    queryKey: ["member", "archived-payments"],
    queryFn: () => staffRequest<ArchivedPaymentSummary[]>("/member/archived-payments"),
    retry: false,
  });
  const unauthenticated = discovery.error instanceof StructuredApiError
    && discovery.error.status === 401;
  // `payments` is a separable app. On a deployment that tombstones it the endpoint is
  // spliced out entirely, so this route must read as absent rather than as a permanent
  // error -- and it cannot ask tenant bootstrap which modules exist, because not depending
  // on bootstrap is the whole reason this route exists. The 404 IS the availability signal.
  const removed = discovery.error instanceof StructuredApiError
    && discovery.error.status === 404;

  if (removed) {
    return (
      <main className="desk-shell grid min-h-[60vh] place-items-center px-5">
        <div className="desk-panel w-full max-w-md p-6 text-center">
          <p className="text-xs font-semibold uppercase tracking-wide text-accent-ink">
            Space Works
          </p>
          <h1 className="mt-2 text-3xl font-bold text-ink">Page not found</h1>
          <Link className="desk-button mt-5 inline-flex" to="/">
            Back to Space Works
          </Link>
        </div>
      </main>
    );
  }

  if (unauthenticated) {
    return (
      <MemberAuthPanel
        onAuthenticated={() => {
          void queryClient.invalidateQueries({
            queryKey: ["member", "archived-payments"],
          });
        }}
      />
    );
  }

  return (
    <main className="desk-shell mx-auto max-w-3xl space-y-5 px-5 py-8">
      <header>
        <p className="text-xs font-semibold uppercase tracking-wide text-accent-ink">
          Archived makerspaces
        </p>
        <h1 className="mt-2 text-3xl font-bold text-ink">Payments and receipts</h1>
        <p className="mt-3 text-sm leading-6 text-muted">
          Closed makerspaces no longer appear in the normal member area. This page remains available so outstanding charges can be settled and past receipts can be read.
        </p>
      </header>

      {discovery.isLoading ? (
        <section className="desk-panel p-5 text-sm text-muted">
          Loading archived makerspace charges…
        </section>
      ) : null}
      {discovery.isError ? (
        <section className="desk-panel p-5">
          <p className="text-sm text-danger" role="alert">
            {errorMessage(discovery.error)}
          </p>
        </section>
      ) : null}
      {discovery.data?.length === 0 ? (
        <section className="desk-panel p-5">
          <h2 className="font-semibold text-ink">No archived payments</h2>
          <p className="mt-1 text-sm text-muted">
            No charges outstanding from closed makerspaces.
          </p>
        </section>
      ) : null}
      {discovery.data?.map((summary) => (
        <ArchivedMakerspacePayments key={summary.makerspace.id} summary={summary} />
      ))}

      <Link className="desk-button inline-flex" to="/">
        Back to Space Works
      </Link>
    </main>
  );
}
