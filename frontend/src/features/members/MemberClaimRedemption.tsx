import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Field } from "../../components/ui";
import { memberRequest, setAccessToken } from "../../lib/api";

export function MemberClaimRedemption({ slug, onRedeemed }: { slug: string; onRedeemed?: () => void }) {
  const client = useQueryClient();
  const [code, setCode] = useState("");
  const redeem = useMutation({
    mutationFn: () => memberRequest<{ access: string }>("/auth/claim/redeem", { method: "POST", body: JSON.stringify({ makerspace_slug: slug, code: code.trim() }) }),
    onSuccess: (result) => {
      setAccessToken(result.access); setCode("");
      // The principal changed. Remove account snapshots without refetching them with
      // the bounded claim token before the parent switches to its local session view.
      client.removeQueries({ queryKey: ["member"] });
      onRedeemed?.();
    },
  });
  return <section className="desk-panel p-5"><h2 className="title-panel">Staff-issued claim code</h2>
    <p className="mt-2 text-sm text-muted">Enter the code handed to you at the desk to open your temporary member session.</p>
    <form className="mt-3 grid gap-3" onSubmit={(event) => { event.preventDefault(); if (code.trim() && !redeem.isPending) redeem.mutate(); }}>
      <Field label="Claim code"><input className="desk-input font-mono" autoComplete="off" required maxLength={64} value={code} disabled={redeem.isPending} onChange={(event) => setCode(event.target.value)} /></Field>
      <button className="desk-button-primary w-fit" disabled={!code.trim() || redeem.isPending}>{redeem.isPending ? "Opening session…" : "Redeem claim code"}</button>
    </form>
    {redeem.isError ? <p role="alert" className="mt-2 text-sm text-danger">{redeem.error.message}</p> : null}
  </section>;
}
