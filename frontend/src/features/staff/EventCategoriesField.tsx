import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";
import { eventOptions } from "./eventTicketingApi";

type Category = { id: number; name: string; slug: string };

export function EventCategoriesField({ makerspaceId, value, onChange, disabled }: {
  makerspaceId: number; value: number | null; onChange: (id: number | null) => void; disabled?: boolean;
}) {
  const client = useQueryClient();
  const key = ["event-categories", makerspaceId];
  const path = `/admin/makerspaces/${makerspaceId}/event-categories/`;
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const categories = useQuery({ queryKey: key, queryFn: () => eventOptions<Category>(path) });
  const create = useMutation({
    mutationFn: () => staffRequest<Category>(path, { method: "POST", body: JSON.stringify({ name, slug }) }),
    onSuccess: async (row) => { await client.invalidateQueries({ queryKey: key }); onChange(row.id); setName(""); setSlug(""); },
  });
  return <div className="grid gap-2 py-3">
    <label>Event category<select className="desk-input" value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}><option value="">No category</option>{categories.data?.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
    <details><summary>Add a category</summary><label>Category name<input className="desk-input" value={name} maxLength={100} disabled={disabled} onChange={(e) => setName(e.target.value)} /></label><label>Category URL name<input className="desk-input" value={slug} maxLength={100} disabled={disabled} onChange={(e) => setSlug(e.target.value)} /></label><button className="desk-button" type="button" disabled={disabled || create.isPending || !name.trim() || !slug.trim()} onClick={() => create.mutate()}>Add category</button></details>
    {categories.error || create.error ? <p role="alert">{(categories.error || create.error)?.message}</p> : null}
  </div>;
}
