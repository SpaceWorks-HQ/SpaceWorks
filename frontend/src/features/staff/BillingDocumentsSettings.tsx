import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Field } from "../../components/ui";
import { staffRequest } from "../../lib/api";

type Billing = { number_prefix: string; legal_name: string; address: string; tax_id: string; footer: string; account_codes: Record<string, string> };

export function BillingDocumentsSettings({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const key = ["billing-policy", makerspaceId];
  const path = `/admin/makerspace/${makerspaceId}/billing-settings`;
  const policy = useQuery({ queryKey: key, queryFn: () => staffRequest<Billing>(path), enabled: expanded });
  const [draft, setDraft] = useState<Billing | null>(null);
  const [codes, setCodes] = useState("");
  useEffect(() => { if (policy.data) { setDraft(policy.data); setCodes(JSON.stringify(policy.data.account_codes, null, 2)); } }, [policy.data]);
  const save = useMutation({
    mutationFn: () => {
      const account_codes: unknown = JSON.parse(codes);
      return staffRequest<Billing>(path, { method: "PATCH", body: JSON.stringify({
        number_prefix: draft?.number_prefix, legal_name: draft?.legal_name, address: draft?.address,
        tax_id: draft?.tax_id, footer: draft?.footer, account_codes,
      }) });
    },
    onSuccess: (data) => { client.setQueryData(key, data); void client.invalidateQueries({ queryKey: ["operations-report", "accounting-journal"] }); },
  });
  return <section className="rounded-md border border-line p-4" aria-label="Billing documents settings">
    <h3 className="title-section">Receipts and accounting</h3>
    <p className="text-sm text-muted">Gross-only acknowledgements. Settings apply to new documents. Existing receipt numbers and snapshots remain unchanged.</p>
    <button className="desk-button-secondary mt-2" type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>Configure documents</button>
    {expanded ? <>
      {policy.isLoading ? <p>Loading billing settings...</p> : null}
      {policy.error || save.error ? <p role="alert" className="text-danger">{(policy.error || save.error)?.message}</p> : null}
      {draft ? <form className="mt-3 grid gap-3" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
        {([ ["number_prefix", "Number prefix", 32], ["legal_name", "Issuer name", 150], ["address", "Issuer address", 1000], ["tax_id", "Issuer identifier (no tax calculation)", 64], ["footer", "Footer", 1000] ] as const).map(([name, label, length]) =>
          <Field key={name} label={label}><input className="desk-input" maxLength={length} value={draft[name]} onChange={(event) => setDraft({ ...draft, [name]: event.target.value })} /></Field>)}
        <Field label="Accounting account codes (JSON)"><textarea className="desk-input font-mono" rows={6} value={codes} onChange={(event) => setCodes(event.target.value)} /></Field>
        <p className="text-xs text-muted">Defaults: income 4000, cash 1000, online 1010, loan-deposit liability 2100. Override individual payment subject types as needed.</p>
        <button className="desk-button" type="submit" disabled={save.isPending}>Save receipt settings</button>
        {save.isSuccess ? <p role="status">Receipt settings saved.</p> : null}
      </form> : null}
    </> : null}
  </section>;
}
