import { useState } from "react";
import { Link } from "react-router-dom";
import { readStorage, writeStorage } from "../../lib/safeStorage";
import { staffTabPath } from "./staffTabs";
import { setupSteps, type SetupState } from "./setupChecklistState";
import { useStaffGet, type Makerspace } from "./panels/shared";

export function SetupChecklist({ makerspace, owner, allowedTabs, guestOnly, singleTenantLocked }: {
  makerspace: Makerspace; owner: string; allowedTabs: readonly string[]; guestOnly: boolean; singleTenantLocked: boolean;
}) {
  const key = `spaceworks.setup.dismissed:${owner}:${makerspace.id}`;
  const [dismissed, setDismissed] = useState(() => readStorage(key) === "true");
  const query = useStaffGet<SetupState>(["setup-state", makerspace.id], `/admin/makerspace/${makerspace.id}/setup-state`, !dismissed);
  if (dismissed) return null;
  const steps = query.data ? setupSteps(query.data, makerspace.enabled_modules ?? []) : [];
  if (steps.length && steps.every(step => step.complete)) return null;
  return <section className="desk-panel mb-5 p-4" aria-labelledby="setup-heading">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="setup-heading" className="title-panel">Set up {makerspace.name}</h2><button className="desk-button-ghost" type="button" onClick={() => { writeStorage(key, "true"); setDismissed(true); }}>Dismiss setup checklist</button></div>
    <p className="mt-2 text-sm text-muted">Progress comes from your makerspace records. Dismissal is remembered for this makerspace on this browser.</p>
    {query.isLoading ? <p role="status">Checking setup…</p> : null}
    {query.error ? <p role="alert" className="text-sm text-danger">Could not check setup: {query.error.message}</p> : null}
    <ul className="mt-3 grid gap-2">{steps.map(step => <li key={step.key} className="flex items-center gap-3 text-sm"><span className={step.complete ? "text-success" : "text-muted"}>{step.complete ? "Done" : "To do"}</span>{allowedTabs.includes(step.tab) ? <Link className="underline focus-visible:outline-2 focus-visible:outline-focus" to={staffTabPath(step.tab, guestOnly, makerspace.slug, singleTenantLocked)}>{step.label}</Link> : <span>{step.label} · ask an administrator</span>}</li>)}</ul>
  </section>;
}
