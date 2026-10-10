import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "../../../../components/ui";
import {
  certificationKeys, getCertificationGrants, getCertificationMembers,
  grantCertification, renewCertification, revokeCertification,
} from "../../certificationsApi";

export function CertificationGrants({ typeId, active }: { typeId: number; active: boolean }) {
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [grantPage, setGrantPage] = useState(1);
  const [member, setMember] = useState("");
  const [notes, setNotes] = useState("");
  const [action, setAction] = useState<{ id: number; kind: "renew" | "revoke" } | null>(null);
  const grants = useQuery({ queryKey: certificationKeys.grants(typeId, grantPage), queryFn: () => getCertificationGrants(typeId, grantPage) });
  const members = useQuery({ queryKey: certificationKeys.members(typeId, page), queryFn: () => getCertificationMembers(typeId, page), enabled: active });
  const mutate = useMutation({
    mutationFn: (input: { id: number; kind: "renew" | "revoke" } | null) => input
      ? (input.kind === "renew" ? renewCertification(input.id, notes) : revokeCertification(input.id, notes))
      : grantCertification(typeId, Number(member), notes),
    onSuccess: async () => {
      setAction(null); setNotes(""); setMember("");
      await Promise.all([
        client.invalidateQueries({ queryKey: certificationKeys.grants(typeId) }),
        client.invalidateQueries({ queryKey: ["member"] }),
      ]);
    },
  });
  return <div className="grid gap-3">
    {grants.isLoading ? <p role="status">Loading training records…</p> : null}
    {grants.isSuccess && !grants.data.count ? <p className="text-sm text-muted">No grants yet.</p> : null}
    <ul className="grid gap-2">{grants.data?.results.map((grant) => <li key={grant.id} className="rounded-lg border border-line p-3 text-sm">
      <strong>{grant.member_name}</strong><p className="text-muted">Granted {new Date(grant.granted_at).toLocaleDateString()} · {grant.revoked_at ? "Revoked" : grant.is_live ? "Valid" : "Expired"} · {grant.expires_at ? `Expires ${new Date(grant.expires_at).toLocaleDateString()}` : "No expiry"}</p>
      {grant.notes ? <p>{grant.notes}</p> : null}
      <div className="mt-2 flex gap-2">{active ? <button className="desk-button-ghost" disabled={mutate.isPending} onClick={() => setAction({ id: grant.id, kind: "renew" })}>Renew</button> : null}{!grant.revoked_at ? <button className="desk-button-danger" disabled={mutate.isPending} onClick={() => setAction({ id: grant.id, kind: "revoke" })}>Revoke</button> : null}</div>
    </li>)}</ul>
    {grants.data && grants.data.count > 24 ? <div className="flex gap-2"><button className="desk-button-ghost" disabled={grantPage === 1 || grants.isFetching} onClick={() => setGrantPage(grantPage - 1)}>Previous grants</button><button className="desk-button-ghost" disabled={!grants.data.next || grants.isFetching} onClick={() => setGrantPage(grantPage + 1)}>More grants</button></div> : null}
    <label className="grid gap-1 text-sm">Training notes / revocation reason<textarea className="desk-input" value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
    {active ? <form className="grid gap-2" onSubmit={(e) => { e.preventDefault(); mutate.mutate(null); }}>
      <label className="grid gap-1 text-sm">Member<select className="desk-input" required value={member} onChange={(e) => setMember(e.target.value)}><option value="">Select a member</option>{members.data?.results.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <div className="flex gap-2"><button type="button" className="desk-button-ghost" disabled={page === 1 || members.isFetching} onClick={() => { setPage(page - 1); setMember(""); }}>Previous members</button><button type="button" className="desk-button-ghost" disabled={!members.data?.next || members.isFetching} onClick={() => { setPage(page + 1); setMember(""); }}>More members</button></div>
      <button className="desk-button-primary w-fit" disabled={!member || mutate.isPending}>{mutate.isPending ? "Saving…" : "Grant certification"}</button>
    </form> : null}
    {[grants.error, members.error, mutate.error].map((error, index) => error instanceof Error ? <p role="alert" className="text-sm text-danger" key={index}>{error.message}</p> : null)}
    <ConfirmDialog open={action !== null} title={action?.kind === "renew" ? "Renew certification?" : "Revoke certification?"} message={action?.kind === "renew" ? "A new grant will record reassessed training from today. The previous record stays in history." : "The member will lose this grant immediately. The training record stays in history."} confirmLabel={action?.kind === "renew" ? "Renew" : "Revoke"} tone={action?.kind === "revoke" ? "danger" : "default"} pending={mutate.isPending} onConfirm={() => { if (action) mutate.mutate(action); }} onCancel={() => setAction(null)} />
  </div>;
}
