import { useEffect, useMemo, useState } from "react";

import type { StaffEvent } from "./eventsApi";
import {
  type BadgeTemplate,
  useEventBadgeTemplate,
  useGenerateEventBadges,
  useSaveEventBadgeTemplate,
} from "./eventsBadgeApi";
import { eventErrorText } from "./eventUi";

const BASE_FIELDS = [
  ["name", "Name"], ["event_title", "Event"], ["date_time", "Date and time"],
  ["location", "Location"], ["registration_number", "Registration number"],
  ["email", "Email (personal)"], ["phone", "Phone (personal)"],
] as const;

function safeFilename(title: string) {
  return `${title.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-|-$/g, "") || "event"}-badges.pdf`;
}

export function EventBadgeActions({ event, makerspaceId, selectedIds, includeAttended, onIncludeAttended }: {
  event: StaffEvent;
  makerspaceId: number;
  selectedIds: number[];
  includeAttended: boolean;
  onIncludeAttended: (value: boolean) => void;
}) {
  const templateQuery = useEventBadgeTemplate(event.id);
  const save = useSaveEventBadgeTemplate(makerspaceId, event.id);
  const generate = useGenerateEventBadges(event.id);
  const [draft, setDraft] = useState<BadgeTemplate | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  useEffect(() => { if (templateQuery.data) setDraft(templateQuery.data); }, [templateQuery.data]);
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);
  const options = useMemo(() => [
    ...BASE_FIELDS,
    ...(event.custom_form ?? []).map((question) => [`custom:${question.id}`, question.label] as const),
  ], [event.custom_form]);
  const error = templateQuery.error || save.error || generate.error;

  function toggleField(selector: string) {
    if (!draft) return;
    const fields = draft.fields.includes(selector)
      ? draft.fields.filter((item) => item !== selector)
      : [...draft.fields, selector];
    if (fields.length) setDraft({ ...draft, fields });
  }

  function savePdf(blob: Blob) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = safeFilename(event.title);
    link.click();
    URL.revokeObjectURL(url);
  }

  const payload = { registration_ids: selectedIds, include_attended: includeAttended };
  const generationDisabled = !selectedIds.length || generate.isPending
    || !["published", "completed"].includes(event.status);

  return <div className="my-4 rounded-md border border-line p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h4 className="font-semibold text-ink">Attendee badges</h4><p className="text-xs text-muted">Each QR contains that registration’s existing check-in credential.</p></div>
      <div className="flex flex-wrap gap-2"><button className="desk-button" type="button" disabled={generationDisabled} onClick={() => generate.mutate(payload, { onSuccess: (blob) => setPreviewUrl(URL.createObjectURL(blob)) })}>Preview</button>
      <button className="desk-button-primary" type="button" disabled={generationDisabled} onClick={() => generate.mutate(payload, { onSuccess: savePdf })}>{generate.isPending ? "Generating…" : `Download PDF (${selectedIds.length})`}</button></div>
    </div>
    <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={includeAttended} onChange={(e) => onIncludeAttended(e.target.checked)} />Allow attended registrations</label>
    {draft ? <details className="mt-3"><summary className="cursor-pointer font-semibold text-ink">Badge template</summary>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-sm">Paper<select className="desk-input mt-1 w-full" value={draft.paper_size} onChange={(e) => setDraft({ ...draft, paper_size: e.target.value as BadgeTemplate["paper_size"] })}><option value="A4">A4</option><option value="LETTER">Letter</option></select></label>
        <label className="text-sm">Orientation<select className="desk-input mt-1 w-full" value={draft.orientation} onChange={(e) => setDraft({ ...draft, orientation: e.target.value as BadgeTemplate["orientation"] })}><option value="portrait">Portrait</option><option value="landscape">Landscape</option></select></label>
        <label className="text-sm">Card width (mm)<input className="desk-input mt-1 w-full" type="number" min="40" max="150" value={draft.card_width_mm} onChange={(e) => setDraft({ ...draft, card_width_mm: Number(e.target.value) })} /></label>
        <label className="text-sm">Card height (mm)<input className="desk-input mt-1 w-full" type="number" min="30" max="120" value={draft.card_height_mm} onChange={(e) => setDraft({ ...draft, card_height_mm: Number(e.target.value) })} /></label>
      </div>
      <fieldset className="mt-3"><legend className="font-semibold text-ink">Printed fields</legend><div className="mt-2 flex flex-wrap gap-x-4 gap-y-2">{options.map(([value, label]) => <label key={value} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.fields.includes(value)} onChange={() => toggleField(value)} />{label}</label>)}</div></fieldset>
      {draft.fields.some((field) => field === "email" || field === "phone") ? <p className="mt-2 text-xs text-danger">This template prints personal contact details. Keep generated PDFs private.</p> : null}
      <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.include_qr} onChange={(e) => setDraft({ ...draft, include_qr: e.target.checked })} />Print check-in QR</label>
      <button className="desk-button mt-3" type="button" disabled={save.isPending} onClick={() => save.mutate(draft)}>{save.isPending ? "Saving…" : "Save template"}</button>
    </details> : null}
    {previewUrl ? <div className="mt-3"><iframe className="h-96 w-full border border-line" src={previewUrl} title="Attendee badge PDF preview" /><button className="desk-button mt-2" type="button" onClick={() => setPreviewUrl(null)}>Close preview</button></div> : null}
    {error ? <p className="mt-2 text-xs text-danger" role="alert">{eventErrorText(error)}</p> : null}
  </div>;
}
