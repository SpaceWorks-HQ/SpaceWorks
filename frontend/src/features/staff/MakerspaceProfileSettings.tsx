import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest, StructuredApiError } from "../../lib/api";
import { MakerspaceHoursEditor } from "./MakerspaceHoursEditor";
import { hoursDraft, serializeHours, validateHours, type MakerspaceProfile } from "./makerspaceProfileForm";

function countryLabel(code: string) {
  return new Intl.DisplayNames(["en"], { type: "region" }).of(code) ?? code;
}

export function MakerspaceProfileSettings({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const currentId = useRef(makerspaceId);
  currentId.current = makerspaceId;
  const path = `/admin/makerspace/${makerspaceId}/profile`;
  const query = useQuery({ queryKey: ["makerspace-profile", makerspaceId], queryFn: () => staffRequest<MakerspaceProfile>(path) });
  const [draft, setDraft] = useState<MakerspaceProfile | null>(null);
  const [baseline, setBaseline] = useState<MakerspaceProfile | null>(null);
  const [hours, setHours] = useState(() => hoursDraft({}));
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => { setDraft(null); setBaseline(null); setDirty(false); setError(null); setSaved(false); }, [makerspaceId]);
  useEffect(() => {
    if (query.data && !dirty) { setDraft(query.data); setBaseline(query.data); setHours(hoursDraft(query.data.opening_hours)); }
  }, [query.data, dirty]);
  const mutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: object }) => staffRequest<MakerspaceProfile>(`/admin/makerspace/${id}/profile`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: (updated, { id }) => {
      client.setQueryData(["makerspace-profile", id], updated);
      if (currentId.current === id) { setDirty(false); setSaved(true); }
      for (const key of [["makerspace-settings", id], ["makerspaces"], ["staff", "makerspaces"], ["tenant-bootstrap"], ["payment-settings", id]]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });
  useEffect(() => { mutation.reset(); }, [makerspaceId, mutation.reset]);
  const changed = () => { setDirty(true); setSaved(false); setError(null); };
  return <section className="min-w-0 rounded-md border border-line bg-bg p-4" aria-labelledby="location-hours-heading">
    <h3 id="location-hours-heading" className="text-base font-semibold text-ink">Location &amp; hours</h3>
    <p className="my-2 text-sm text-muted">Times use this makerspace&apos;s timezone. Hours are informational until a workflow uses them. Currency is the same default used by payment settings; existing charges keep their currency. Country stays private to staff.</p>
    {query.isPending ? <p role="status">Loading profile...</p> : null}
    {query.error ? <p role="alert">{query.error.message} <button className="desk-button" type="button" onClick={() => void query.refetch()}>Retry</button></p> : null}
    {draft ? <form className="grid gap-4" onSubmit={event => {
      event.preventDefault();
      const invalid = validateHours(hours) ?? (!/^[a-z]{3}$/.test(draft.default_currency) ? "Enter a three-letter currency code." : null);
      setError(invalid);
      if (!invalid && dirty && !mutation.isPending) {
        const body: Record<string, unknown> = {};
        const openingHours = serializeHours(hours);
        if (JSON.stringify(openingHours) !== JSON.stringify(serializeHours(hoursDraft(baseline?.opening_hours ?? {})))) {
          body.opening_hours = openingHours;
        }
        for (const field of ["timezone", "country", "default_currency"] as const) {
          if (draft[field] !== baseline?.[field]) body[field] = draft[field];
        }
        mutation.mutate({ id: makerspaceId, body });
      }
    }}>
      <fieldset className="grid gap-4" disabled={mutation.isPending}>
        <legend className="sr-only">Profile fields</legend>
        <label className="grid gap-1 text-sm font-semibold">Timezone
          <select className="desk-input" value={draft.timezone} onChange={event => { changed(); setDraft({ ...draft, timezone: event.target.value }); }}>
            {draft.timezone_choices.map(zone => <option key={zone}>{zone}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-semibold">Country
          <select className="desk-input" value={draft.country} onChange={event => { changed(); setDraft({ ...draft, country: event.target.value }); }}>
            <option value="">Unspecified</option>
            {draft.country_choices.map(code => <option key={code} value={code}>{countryLabel(code)}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-semibold">Default currency
          <input className="desk-input" maxLength={3} value={draft.default_currency} onChange={event => { changed(); setDraft({ ...draft, default_currency: event.target.value.toLowerCase() }); }} />
        </label>
        <MakerspaceHoursEditor value={hours} onChange={value => { changed(); setHours(value); }} />
      </fieldset>
      {error ? <p role="alert" className="text-danger">{error}</p> : null}
      {mutation.error ? <p role="alert" className="text-danger">{mutation.error.message}{mutation.error instanceof StructuredApiError && mutation.error.body.fields && typeof mutation.error.body.fields === "object" ? ` ${Object.entries(mutation.error.body.fields).map(([field, messages]) => `${field}: ${messages}`).join("; ")}` : ""}</p> : null}
      {saved ? <p role="status">Saved.</p> : null}
      <button className="desk-button-primary w-fit" disabled={!dirty || mutation.isPending} type="submit">{mutation.isPending ? "Saving..." : "Save location & hours"}</button>
    </form> : null}
  </section>;
}
