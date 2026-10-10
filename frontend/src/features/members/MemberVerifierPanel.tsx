import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Field } from "../../components/ui";
import { memberRequest } from "../../lib/api";

export function MemberVerifierPanel({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const [membershipId, setMembershipId] = useState("");
  const verify = useMutation({
    mutationFn: (verified: boolean) => memberRequest<{ display_name: string }>(`/member/makerspaces/${makerspaceId}/verification`, { method: "POST", body: JSON.stringify({ membership_id: Number(membershipId), verified }) }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["member"] }); },
  });
  const valid = /^[1-9]\d*$/.test(membershipId);
  return <section className="desk-panel p-5"><h2 className="title-panel">Member verification</h2>
    <p className="mt-2 text-sm text-muted">Enter the membership ID supplied by staff. You can verify members in your makerspace; you cannot verify yourself.</p>
    <Field label="Membership ID"><input className="desk-input" inputMode="numeric" value={membershipId} onChange={(event) => { setMembershipId(event.target.value); verify.reset(); }} disabled={verify.isPending} /></Field>
    <div className="mt-3 flex gap-2"><button className="desk-button-primary" disabled={!valid || verify.isPending} onClick={() => verify.mutate(true)}>Verify member</button>
      <button className="desk-button" disabled={!valid || verify.isPending} onClick={() => verify.mutate(false)}>Remove verification</button></div>
    {verify.isPending ? <p role="status" className="text-sm text-muted">Updating verification…</p> : null}
    {verify.isSuccess ? <p role="status" className="text-sm text-success">Verification {verify.variables ? "recorded" : "removed"} for {verify.data.display_name}.</p> : null}
    {verify.isError ? <p role="alert" className="text-sm text-danger">{verify.error.message}</p> : null}
  </section>;
}
