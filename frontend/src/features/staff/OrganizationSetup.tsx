import { useState } from "react";
import { ConfirmDialog } from "../../components/ui";
import type { Makerspace } from "./panels/shared";
import { useChangeOrganizationLink, useCreateOrganization, useOrganizationLinks, type OrganizationLink } from "./organizationsApi";

export function OrganizationCreate({ onCreated }: { onCreated: (id: number) => void }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const create = useCreateOrganization();
  return <form className="mb-4 grid gap-3 rounded border border-line p-4" onSubmit={event => { event.preventDefault(); create.mutate({ name: name.trim(), slug: slug.trim() }, { onSuccess: row => { onCreated(row.id); setName(""); setSlug(""); } }); }}>
    <h3 className="title-section">Create organization</h3>
    <label>Name<input className="desk-input block w-full" required maxLength={200} value={name} onChange={event => setName(event.target.value)} /></label>
    <label>Slug<input className="desk-input block w-full" required pattern="[-a-zA-Z0-9_]+" maxLength={50} value={slug} onChange={event => setSlug(event.target.value)} /></label>
    <button className="desk-button-primary" disabled={create.isPending || !name.trim() || !slug.trim()}>Create organization</button>
    {create.error ? <p role="alert" className="text-danger">{create.error.message}</p> : null}
  </form>;
}

export function OrganizationLinks({ id, makerspaces }: { id: number; makerspaces: Makerspace[] }) {
  const [page, setPage] = useState(1);
  const links = useOrganizationLinks(id, true, page);
  const change = useChangeOrganizationLink(id);
  const [space, setSpace] = useState("");
  const [relationship, setRelationship] = useState<OrganizationLink["relationship"]>("affiliate");
  const [pending, setPending] = useState<{ makerspace_id: number; relationship?: OrganizationLink["relationship"] } | null>(null);
  return <section className="grid gap-3 rounded border border-line p-4">
    <h3 className="title-section">Linked makerspaces</h3>
    <p className="text-sm text-muted">Linking a space extends the organization's granted actions to it. Relationship labels describe the connection; all three can confer those actions.</p>
    <label>Makerspace<select className="desk-input block w-full" value={space} onChange={event => setSpace(event.target.value)}><option value="">Choose space</option>{makerspaces.filter(row => row.superadmin_access_enabled !== false).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
    <label>Relationship<select className="desk-input block" value={relationship} onChange={event => setRelationship(event.target.value as OrganizationLink["relationship"])}>{["affiliate", "manager", "owner"].map(value => <option key={value}>{value}</option>)}</select></label>
    <button className="desk-button" disabled={!space || change.isPending} onClick={() => setPending({ makerspace_id: Number(space), relationship })}>Link or update relationship</button>
    {links.isLoading ? <p role="status">Loading links…</p> : null}
    {links.error || change.error ? <p role="alert" className="text-danger">{(links.error ?? change.error)?.message}</p> : null}
    <ul className="grid gap-2">{links.data?.results.map(row => <li key={row.id} className="flex flex-wrap items-center gap-3">{row.makerspace_name} · {row.relationship}<button className="desk-button-danger" disabled={change.isPending} onClick={() => setPending({ makerspace_id: row.makerspace_id })}>Unlink</button></li>)}</ul>
    <div className="flex gap-2"><button className="desk-button" disabled={!links.data?.previous} onClick={() => setPage(page - 1)}>Previous</button><button className="desk-button" disabled={!links.data?.next} onClick={() => setPage(page + 1)}>Next</button></div>
    <ConfirmDialog open={Boolean(pending)} title={pending?.relationship ? "Change organization reach?" : "Unlink makerspace?"} message="This changes which spaces organization members can act in." confirmLabel="Confirm" onCancel={() => setPending(null)} onConfirm={() => { if (pending) change.mutate(pending, { onSuccess: () => setPending(null) }); }} pending={change.isPending} />
  </section>;
}
