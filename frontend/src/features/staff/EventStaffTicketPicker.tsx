import { useQuery } from "@tanstack/react-query";
import { eventOptions } from "./eventTicketingApi";
import type { StaffTicket } from "./eventTicketingApi";

export function EventStaffTicketPicker({ eventId, value, onChange }: {
  eventId: number; value: string; onChange: (value: string) => void;
}) {
  const rows = useQuery({ queryKey: ["event", eventId, "ticket-types", "all"], queryFn: () => eventOptions<StaffTicket>(`/admin/events/${eventId}/ticket-types/`) });
  return <label className="grid gap-1 text-sm">Ticket type<select className="desk-input" value={value} onChange={(e) => onChange(e.target.value)}><option value="">Choose a ticket</option>{rows.data?.map((ticket) => <option key={ticket.id} value={ticket.id}>{ticket.name} · {ticket.amount} · {ticket.audience}</option>)}</select>{rows.error ? <span role="alert">{rows.error.message}</span> : null}</label>;
}
