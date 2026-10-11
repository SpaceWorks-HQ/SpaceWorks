import { useEffect, useState } from "react";
import { Modal } from "../../../../components/ui";
import { hoursDraft, validateHours } from "../../makerspaceProfileForm";
import { CreationWizardSteps } from "./CreationWizardSteps";
import type { MakerspaceForm } from "./types";

const steps = ["Identity", "Profile and hours", "Modules and pack", "First staff", "Review"];
export function CreateMakerspaceModal({ open, form, pending, error, onChange, onClose, onSubmit }: {
  open: boolean; form: MakerspaceForm; pending: boolean; error: unknown;
  onChange: (form: MakerspaceForm) => void; onClose: () => void; onSubmit: () => void;
}) {
  const [step, setStep] = useState(0);
  const [invalid, setInvalid] = useState<string | null>(null);
  useEffect(() => { if (open) { setStep(0); setInvalid(null); } }, [open]);
  const validate = () => {
    if (!form.name.trim() || !/^[A-Z0-9]{4}$/.test(form.public_code) || !/^[-a-zA-Z0-9_]+$/.test(form.slug)) return "Enter a name, a four-character public code and a valid slug.";
    if (form.profile) {
      if (form.profile.timezone !== undefined) {
        try { new Intl.DateTimeFormat("en", { timeZone: form.profile.timezone }); } catch { return "Choose a valid timezone."; }
      }
      if (form.profile.default_currency !== undefined && !/^[a-z]{3}$/.test(form.profile.default_currency)) return "Enter a three-letter currency code.";
      const hoursError = form.profile.opening_hours === undefined ? null : validateHours(hoursDraft(form.profile.opening_hours));
      if (hoursError) return hoursError;
    }
    if (form.first_staff_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.first_staff_email.trim())) return "Enter a valid staff email.";
    return null;
  };
  return <Modal open={open} onClose={() => { if (!pending) onClose(); }} title="Create makerspace" footer={<div className="desk-actions flex flex-wrap gap-2">
    <button type="button" className="desk-button-ghost" disabled={pending} onClick={onClose}>Cancel</button>
    {step > 0 ? <button type="button" className="desk-button" disabled={pending} onClick={() => { setStep(step - 1); setInvalid(null); }}>Back</button> : null}
    <button type="submit" form="makerspace-creation-wizard" className="desk-button-primary" disabled={pending}>{pending ? "Creating…" : step === 4 ? "Create makerspace" : "Next"}</button>
  </div>}>
    <p role="status" className="mb-3 text-sm">Step {step + 1} of {steps.length}: {steps[step]}</p>
    <form id="makerspace-creation-wizard" className="grid gap-3" onSubmit={event => {
      event.preventDefault(); if (pending) return;
      const message = validate(); setInvalid(message); if (message) return;
      if (step < 4) setStep(step + 1); else onSubmit();
    }}>
      <fieldset className="grid gap-3" disabled={pending}><legend className="sr-only">{steps[step]}</legend><CreationWizardSteps step={step} form={form} onChange={onChange} pending={pending} /></fieldset>
      {invalid || error ? <p role="alert" className="text-sm text-danger">{invalid ?? (error instanceof Error ? error.message : "Creation failed. Check the fields and retry.")}</p> : null}
    </form>
  </Modal>;
}
