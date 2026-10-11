import { tenantPublicRequestBlob } from "../../lib/api";

export async function downloadEventCalendar(slug: string, event: { public_token: string; title: string }) {
  const blob = await tenantPublicRequestBlob(slug, `/public/${encodeURIComponent(slug)}/events/${encodeURIComponent(event.public_token)}/calendar.ics`);
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = `${event.title.replace(/[^A-Za-z0-9._-]+/g, "-") || "event"}.ics`;
    link.click();
  } finally { URL.revokeObjectURL(url); }
}
