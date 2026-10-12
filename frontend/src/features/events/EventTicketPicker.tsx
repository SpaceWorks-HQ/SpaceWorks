import type { EventTicket } from "./eventTicketTypes";

export function EventTicketPicker({ tickets, value, onChange, currency, disabled = false }: {
  tickets: EventTicket[]; value: number | null; onChange: (id: number | null) => void;
  currency: string; disabled?: boolean;
}) {
  if (!tickets.length) return null;
  return <label className="grid gap-1 text-sm font-semibold">Ticket type
    <select className="desk-input" required value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">Choose a ticket</option>
      {tickets.map((ticket) => <option key={ticket.id} value={ticket.id}>
        {ticket.name} · {Number(ticket.amount) === 0 ? "Free" : `${ticket.amount} ${currency}`}{ticket.spots_left === 0 ? " · Waitlist" : ""}
      </option>)}
    </select>
  </label>;
}
