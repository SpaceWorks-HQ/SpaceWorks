import { useState } from "react";
import { useEventTicketing, type EventPromo } from "./eventTicketingApi";

export function EventPromosPanel({ eventId, disabled = false }: { eventId: number; disabled?: boolean }) {
  const [page, setPage] = useState(1);
  const { rows, create, revoke } = useEventTicketing<EventPromo>(eventId, "promo-codes", page);
  const [mode, setMode] = useState("percent");
  const [amount, setAmount] = useState("5.00");
  const [customCode, setCustomCode] = useState("");
  const [percent, setPercent] = useState(20);
  const [limit, setLimit] = useState(1);
  const [expiry, setExpiry] = useState("");
  const [code, setCode] = useState("");
  return <section className="grid gap-3" aria-label="Event promo codes">
    <h3 className="title-section">Promo codes</h3>
    <form className="grid gap-2" onSubmit={(e) => { e.preventDefault(); create.mutate({ ...(mode === "percent" ? { percent_off: percent } : { amount_off: amount }), ...(customCode ? { code: customCode } : {}), max_uses: limit, expires_at: expiry ? new Date(expiry).toISOString() : null }, { onSuccess: (row) => setCode(row.code ?? "") }); }}>
      <label>Discount type<select className="desk-input" value={mode} disabled={disabled} onChange={(e) => setMode(e.target.value)}><option value="percent">Percentage</option><option value="amount">Fixed amount</option></select></label>
      <label>Code (optional)<input className="desk-input" minLength={8} maxLength={128} value={customCode} disabled={disabled} onChange={(e) => setCustomCode(e.target.value)} /></label>
      {mode === "percent" ? <label>Percent discount<input className="desk-input" type="number" required min="1" max="100" value={percent} disabled={disabled} onChange={(e) => setPercent(Number(e.target.value))} /></label> : <label>Amount discount<input className="desk-input" type="number" required min="0.01" step="0.01" value={amount} disabled={disabled} onChange={(e) => setAmount(e.target.value)} /></label>}
      <label>Maximum redemptions<input className="desk-input" type="number" required min="1" value={limit} disabled={disabled} onChange={(e) => setLimit(Number(e.target.value))} /></label>
      <label>Promo expiry<input className="desk-input" type="datetime-local" value={expiry} disabled={disabled} onChange={(e) => setExpiry(e.target.value)} /></label>
      <button className="desk-button" disabled={disabled || create.isPending}>Create promo code</button>
    </form>
    {code ? <div role="status">Copy this code now. It is shown once: <output className="font-mono break-all">{code}</output><button className="desk-button" onClick={() => setCode("")}>Hide code</button></div> : null}
    {rows.error || create.error || revoke.error ? <p role="alert">{(rows.error || create.error || revoke.error)?.message}</p> : null}
    {rows.isLoading ? <p role="status">Loading promo codes...</p> : null}
    <ul>{rows.data?.results.map((row) => <li key={row.id}>Promo {row.id} ({row.percent_off ? `${row.percent_off}%` : row.amount_off} discount) · {row.uses}/{row.max_uses} uses {row.revoked_at ? "· Revoked" : <button className="desk-button-danger" disabled={disabled || revoke.isPending} onClick={() => revoke.mutate(row.id)}>Revoke promo {row.id}</button>}</li>)}</ul>
    <div><button className="desk-button" disabled={!rows.data?.previous} onClick={() => setPage(page - 1)}>Previous</button><button className="desk-button" disabled={!rows.data?.next} onClick={() => setPage(page + 1)}>Next</button></div>
  </section>;
}
