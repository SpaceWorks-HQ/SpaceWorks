import { useEffect, useState, type FormEvent } from "react";

import type { OrganizationDetail } from "./organizationsApi";
import { useUpdateOrganization } from "./organizationsApi";

export function OrganizationProfileForm({ organization }: { organization: OrganizationDetail }) {
  const [values, setValues] = useState({
    name: organization.name,
    slug: organization.slug,
    description: organization.description,
    website: organization.website,
    public_profile_enabled: organization.public_profile_enabled,
  });
  const update = useUpdateOrganization(organization.id, organization.slug);
  const allowed = organization.governance_actions.includes("manage_organization_profile");

  useEffect(() => {
    setValues({
      name: organization.name,
      slug: organization.slug,
      description: organization.description,
      website: organization.website,
      public_profile_enabled: organization.public_profile_enabled,
    });
  }, [organization]);

  function submit(event: FormEvent) {
    event.preventDefault();
    update.mutate(values);
  }

  return (
    <form className="rounded-xl border border-line bg-bg p-4" onSubmit={submit}>
      <div className="mb-3">
        <h3 className="title-section">Public profile</h3>
        <p className="mt-1 text-sm text-muted">Controls the organization directory page. Logo upload remains platform-managed.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-sm font-semibold text-ink">Name
          <input className="desk-input" maxLength={200} disabled={!allowed} value={values.name} onChange={(event) => setValues({ ...values, name: event.target.value })} />
        </label>
        <label className="grid gap-1 text-sm font-semibold text-ink">Public slug
          <input className="desk-input" disabled={!allowed} value={values.slug} onChange={(event) => setValues({ ...values, slug: event.target.value })} />
        </label>
        <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Website
          <input className="desk-input" type="url" disabled={!allowed} value={values.website} onChange={(event) => setValues({ ...values, website: event.target.value })} />
        </label>
        <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Description
          <textarea className="desk-input min-h-28" disabled={!allowed} value={values.description} onChange={(event) => setValues({ ...values, description: event.target.value })} />
        </label>
        <label className="flex items-center gap-2 text-sm text-ink sm:col-span-2">
          <input type="checkbox" disabled={!allowed} checked={values.public_profile_enabled} onChange={(event) => setValues({ ...values, public_profile_enabled: event.target.checked })} />
          Publish this organization profile and its eligible event catalogue
        </label>
      </div>
      {allowed ? <button className="desk-button-primary mt-4" type="submit" disabled={update.isPending}>{update.isPending ? "Saving..." : "Save profile"}</button> : <p className="mt-4 text-sm text-muted">You have view-only access to this profile.</p>}
      {update.error ? <p className="mt-2 text-sm text-danger" role="alert">{update.error.message}</p> : null}
    </form>
  );
}
