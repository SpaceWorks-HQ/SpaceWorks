import { Field } from "../../../../components/ui";
import { MakerspaceHoursEditor } from "../../MakerspaceHoursEditor";
import { hoursDraft, serializeHours } from "../../makerspaceProfileForm";
import { SpacePackProfilePicker } from "../../SpacePackProfilePicker";
import type { MakerspaceForm } from "./types";

export const defaultCreationProfile = { timezone: "UTC", country: "", default_currency: "usd", opening_hours: {} };
const modules = [["events", "Events"], ["bookings", "Bookings"], ["machines", "Machines"], ["maintenance", "Maintenance"], ["membership", "Membership"], ["printing", "Printing"], ["payments", "Online payments"], ["reports", "Reports"], ["notifications", "Notifications"]] as const;

export function CreationWizardSteps({ step, form, onChange, pending }: { step: number; form: MakerspaceForm; onChange: (form: MakerspaceForm) => void; pending: boolean }) {
  const profile = { ...defaultCreationProfile, ...form.profile };
  if (step === 0) return <>
    {(["name", "public_code", "slug", "location"] as const).map(key => <Field key={key} label={{ name: "Name", public_code: "Public code", slug: "Slug", location: "Location" }[key]}>
      <input className="desk-input w-full" required={key !== "location"} maxLength={key === "public_code" ? 4 : key === "slug" ? 50 : 200} value={form[key]} onChange={event => onChange({ ...form, [key]: key === "public_code" ? event.target.value.toUpperCase() : event.target.value })} />
    </Field>)}
    <p className="text-xs text-muted">Create with platform access enabled. Hidden spaces require two verified archive recipients before access can be disabled.</p>
  </>;
  if (step === 1) return <>
    <p className="text-sm text-muted">Leave these unchanged to use the deployment or saved pack profile. Editing them explicitly overrides the pack.</p>
    {(["timezone", "country", "default_currency"] as const).map(key => <Field key={key} label={{ timezone: "Timezone", country: "Country code", default_currency: "Currency" }[key]}>
      <input className="desk-input w-full" value={profile[key]} maxLength={key === "timezone" ? 100 : key === "country" ? 2 : 3} onChange={event => onChange({ ...form, profile: { ...form.profile, [key]: key === "country" ? event.target.value.toUpperCase() : key === "default_currency" ? event.target.value.toLowerCase() : event.target.value } })} />
    </Field>)}
    <MakerspaceHoursEditor value={hoursDraft(profile.opening_hours)} onChange={hours => onChange({ ...form, profile: { ...form.profile, opening_hours: serializeHours(hours) } })} />
  </>;
  if (step === 2) return <>
    <SpacePackProfilePicker value={form.install_profile_id ?? ""} disabled={pending} onChange={pack => onChange({ ...form, install_profile_id: pack?.id ?? "" })} />
    <p className="text-sm text-muted">Core modules remain installed. The server adds dependencies and refuses modules this deployment does not ship.</p>
    <label className="flex min-h-11 gap-2"><input type="checkbox" checked={form.modules !== undefined} onChange={event => onChange({ ...form, modules: event.target.checked ? [] : undefined })} />Choose module families instead of the deployment or saved pack defaults</label>
    {form.modules ? modules.map(([key, label]) => <label key={key} className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={form.modules!.includes(key)} onChange={event => onChange({ ...form, modules: event.target.checked ? [...form.modules!, key] : form.modules!.filter(value => value !== key) })} />{label}</label>) : null}
  </>;
  if (step === 3) return <>
    <p className="text-sm text-muted">Optional: send the first staff invitation after the makerspace is created. Delivery failures provide a private link.</p>
    <Field label="First staff email"><input className="desk-input w-full" type="email" value={form.first_staff_email ?? ""} onChange={event => onChange({ ...form, first_staff_email: event.target.value })} /></Field>
    <Field label="First staff role"><select className="desk-input w-full" value={form.first_staff_role ?? "space_manager"} onChange={event => onChange({ ...form, first_staff_role: event.target.value as MakerspaceForm["first_staff_role"] })}>
      <option value="space_manager">Space Manager</option><option value="inventory_manager">Inventory Manager</option><option value="machine_manager">Machine Manager</option>
    </select></Field>
  </>;
  return <dl className="grid gap-2 text-sm"><dt>Name</dt><dd>{form.name}</dd><dt>Public address</dt><dd>/m/{form.slug}</dd><dt>Profile overrides</dt><dd>{form.profile ? Object.entries(form.profile).map(([key, value]) => key === "opening_hours" ? "Opening hours" : `${key}: ${value}`).join(", ") : "Deployment or saved pack defaults"}</dd><dt>Modules</dt><dd>{form.modules?.join(", ") || (form.modules ? "Core only" : "Deployment or saved pack defaults")}</dd><dt>Saved pack</dt><dd>{form.install_profile_id || "None"}</dd><dt>First staff</dt><dd>{form.first_staff_email || "Invite later"}</dd></dl>;
}
