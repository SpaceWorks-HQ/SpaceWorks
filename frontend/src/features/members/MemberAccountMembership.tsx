import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountKey, endMembership, ownMembership } from "./memberAccountApi";

export function MemberAccountMembership({ makerspaceId, onLeft }: { makerspaceId: number; onLeft: () => void }) {
  const [action, setAction] = useState<"cancel" | "leave" | null>(null);
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const membership = useQuery({ queryKey: [...accountKey(makerspaceId), "membership"], queryFn: () => ownMembership(makerspaceId), retry: false });
  const change = useMutation({ mutationFn: () => endMembership(makerspaceId, action!, reason), onSuccess: () => {
    void client.invalidateQueries({ queryKey: ["member"] });
    if (action === "leave") onLeft();
    setAction(null); setReason("");
  } });
  return <section className="desk-panel p-5"><h2 className="title-panel">Your membership</h2>
    {membership.isLoading ? <p role="status">Loading membership…</p> : null}
    {membership.data?.renewal_cancelled_at ? <p role="status">Renewal is cancelled. Your current term remains available until it ends.</p> : null}
    <p className="text-sm text-muted mt-2">Cancel renewal to keep your current term. Leaving ends your membership immediately. Existing loans and payment records remain on file.</p>
    {membership.data ? <div className="flex flex-wrap gap-2 mt-3"><button className="desk-button-secondary" disabled={Boolean(membership.data.renewal_cancelled_at) || change.isPending} onClick={() => { change.reset(); setAction("cancel"); }}>Cancel renewal</button><button className="desk-button-secondary" disabled={change.isPending} onClick={() => { change.reset(); setAction("leave"); }}>Leave makerspace</button></div> : null}
    {action ? <form className="mt-4 grid gap-3" onSubmit={(event) => { event.preventDefault(); change.mutate(); }}>
      <label className="text-sm">Reason<textarea className="desk-input mt-1" required maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      <p>{action === "leave" ? "Confirm that you want to leave this makerspace now." : "Confirm that you want to stop future renewal."}</p>
      <div className="flex gap-2"><button className="desk-button-primary" disabled={!reason.trim() || change.isPending}>Confirm {action === "leave" ? "leave" : "cancellation"}</button><button type="button" className="desk-button" disabled={change.isPending} onClick={() => setAction(null)}>Keep membership</button></div>
    </form> : null}
    {membership.error || change.error ? <p role="alert" className="text-danger">{(membership.error || change.error)?.message}</p> : null}
  </section>;
}
