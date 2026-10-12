import { useMutation } from "@tanstack/react-query";
import { tenantPublicRequest } from "../../lib/api";

export function NotifyWhenBack({ slug, productId }: { slug: string; productId: number }) {
  const subscription = useMutation({
    throwOnError: false,
    mutationFn: () => tenantPublicRequest<{ subscribed: boolean }>(slug,
      `/public/${encodeURIComponent(slug)}/inventory/${productId}/watch/`,
      { method: "POST", body: JSON.stringify({}) }),
  });
  const cancel = useMutation({
    throwOnError: false,
    mutationFn: () => tenantPublicRequest(slug,
      `/public/${encodeURIComponent(slug)}/inventory/${productId}/watch/`, { method: "DELETE" }),
    onSuccess: () => subscription.reset(),
  });
  return <div className="mt-4">
    <button className="desk-button" type="button" disabled={subscription.isPending || cancel.isPending}
      onClick={() => subscription.isSuccess ? cancel.mutate() : subscription.mutate()}>
      {subscription.isSuccess ? "Cancel notification" : subscription.isPending ? "Saving…" : "Notify me when back"}
    </button>
    {subscription.isSuccess ? <p role="status" className="mt-2 text-sm text-muted">We’ll notify your member account when stock rises. Sign in as an active member to subscribe.</p> : null}
    {subscription.error || cancel.error ? <p role="alert" className="mt-2 text-sm text-danger">{(subscription.error || cancel.error)?.message}</p> : null}
  </div>;
}
