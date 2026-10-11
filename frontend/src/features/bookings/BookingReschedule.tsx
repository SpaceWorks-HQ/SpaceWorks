import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { memberRequest } from "../../lib/api";
import type { MemberBooking } from "./MyBookings";

export function BookingReschedule({ booking, slug, onClose }: { booking: MemberBooking; slug: string; onClose: () => void }) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const client = useQueryClient();
  const save = useMutation({ mutationFn: () => memberRequest<MemberBooking>(`/public/${encodeURIComponent(slug)}/my-bookings/${booking.public_token}/reschedule/`, {
    method: "POST", body: JSON.stringify({ starts_at: new Date(start).toISOString(), ends_at: new Date(end).toISOString() }),
  }), onSuccess: async () => {
    await Promise.all([client.invalidateQueries({ queryKey: ["member", slug] }), client.invalidateQueries({ queryKey: ["public-space-availability"] })]);
    onClose();
  } });
  return <form className="mt-3 grid gap-2 rounded-lg border border-line p-3" aria-label="Reschedule booking" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <p className="text-sm">Move {booking.space_name}. The charge and approval status stay the same.</p>
    <label className="grid gap-1 text-sm">New start (your local time)<input className="desk-input" type="datetime-local" required value={start} onChange={(event) => setStart(event.target.value)} /></label>
    <label className="grid gap-1 text-sm">New end (your local time)<input className="desk-input" type="datetime-local" required min={start} value={end} onChange={(event) => setEnd(event.target.value)} /></label>
    {save.error ? <p role="alert" className="text-danger">{save.error.message}</p> : null}
    <div className="flex gap-2"><button className="desk-button-primary" disabled={save.isPending}>Save new time</button><button className="desk-button-ghost" type="button" disabled={save.isPending} onClick={onClose}>Keep current time</button></div>
  </form>;
}
