import type { EventTicket } from "./eventTicketTypes";

/** Display the configured price with the host's currency on public catalogues. */
export function EventPrice({ amount, currency, tickets = [], ticketRequired = false }: { amount: string; currency: string; tickets?: EventTicket[]; ticketRequired?: boolean }) {
  const prices = tickets.map((ticket) => Number(ticket.amount));
  const lowest = prices.length ? Math.min(...prices) : Number(amount);
  const prefix = prices.length && Math.max(...prices) !== lowest ? "From " : "";
  const label = lowest === 0 ? "Free" : `${lowest.toFixed(2)} ${currency.toUpperCase()}`;
  return <div><dt className="eyebrow">Price</dt><dd className="font-mono font-semibold text-ink">
    {ticketRequired && !tickets.length ? "No tickets available" : `${prefix}${label}`}
  </dd></div>;
}
