export type TicketTemplate = { name: string; amount: string; audience: "public" | "member"; capacity: number; sales_start_at?: string | null; sales_end_at?: string | null };

/** Templates are copied when occurrences are materialized; existing sales stay intact. */
export function EventTicketTemplates({ value, onChange, disabled = false }: {
  value: TicketTemplate[]; onChange: (tickets: TicketTemplate[]) => void; disabled?: boolean;
}) {
  return <fieldset className="grid gap-2"><legend className="title-section">Ticket templates</legend>
    {value.map((ticket, index) => {
      const update = (changes: Partial<TicketTemplate>) => onChange(value.map((row, i) => i === index ? { ...row, ...changes } : row));
      return <div className="grid gap-2 rounded border border-line p-3" key={index}>
        <label>Ticket name<input className="desk-input" required maxLength={100} value={ticket.name} disabled={disabled} onChange={(e) => update({ name: e.target.value })} /></label>
        <label>Ticket price<input className="desk-input" type="number" min="0" step="0.01" value={ticket.amount} disabled={disabled} onChange={(e) => update({ amount: e.target.value })} /></label>
        <label>Ticket audience<select className="desk-input" value={ticket.audience} disabled={disabled} onChange={(e) => update({ audience: e.target.value as TicketTemplate["audience"] })}><option value="public">All accounts</option><option value="member">Active members</option></select></label>
        <label>Ticket capacity<input className="desk-input" type="number" min="0" value={ticket.capacity} disabled={disabled} onChange={(e) => update({ capacity: Number(e.target.value) })} /></label>
        <label>Ticket sales start<input className="desk-input" type="datetime-local" value={ticket.sales_start_at ?? ""} disabled={disabled} onChange={(e) => update({ sales_start_at: e.target.value })} /></label>
        <label>Ticket sales end<input className="desk-input" type="datetime-local" value={ticket.sales_end_at ?? ""} disabled={disabled} onChange={(e) => update({ sales_end_at: e.target.value })} /></label>
        <button className="desk-button-danger" type="button" disabled={disabled} onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove ticket</button>
      </div>;
    })}
    <button className="desk-button" type="button" disabled={disabled} onClick={() => onChange([...value, { name: "", amount: "0.00", audience: "public", capacity: 0 }])}>Add ticket template</button>
  </fieldset>;
}
