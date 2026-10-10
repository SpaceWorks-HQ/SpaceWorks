import { useState, type FormEvent } from "react";

import { BookableSpaceMachineType } from "./BookableSpaceMachineType";
import { CustomFormBuilder } from "../forms/CustomFormBuilder";
import type { CustomFormSchema } from "../forms/customFormTypes";
import type { BookableSpace, BookableSpacePayload } from "./bookingsApi";

type FormValues = BookableSpacePayload;

export const EMPTY_SPACE_FORM: FormValues = {
  name: "",
  kind: "other",
  description: "",
  capacity: 0,
  location: "",
  is_public: false,
  show_public_availability: false,
  show_public_booker_names: false,
  approval_mode: "instant",
  payment_amount: "0.00",
  custom_form: null,
  requester_notifications_enabled: null,
  machine_type: null,
};

export function valuesForSpace(space: BookableSpace): FormValues {
  return {
    name: space.name,
    kind: space.kind,
    description: space.description,
    capacity: space.capacity,
    location: space.location,
    is_public: space.is_public,
    show_public_availability: space.show_public_availability,
    show_public_booker_names: space.show_public_booker_names,
    approval_mode: space.approval_mode,
    payment_amount: space.payment_amount,
    custom_form: space.custom_form,
    requester_notifications_enabled: space.requester_notifications_enabled,
    machine_type: space.machine_type ?? null,
  };
}

export function BookableSpaceForm({ makerspaceId, initialValues = EMPTY_SPACE_FORM, onSubmit, pending, error, submitLabel, disabled = false }: {
  makerspaceId?: number;
  initialValues?: FormValues;
  onSubmit: (payload: BookableSpacePayload) => void;
  pending: boolean;
  error?: string;
  submitLabel: string;
  disabled?: boolean;
}) {
  const [values, setValues] = useState<FormValues>(initialValues);
  const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) => setValues((current) => ({ ...current, [key]: value }));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const payload: BookableSpacePayload = {
      ...values,
      name: values.name.trim(),
      description: values.description.trim(),
      location: values.location.trim(),
      custom_form: values.custom_form?.length ? values.custom_form : null,
    };
    // An unchanged link must survive editing while Machines is uninstalled.
    // The server validates machine_type only when the caller actually changes it.
    if (values.machine_type === initialValues.machine_type) delete payload.machine_type;
    onSubmit(payload);
  };
  const changeAvailability = (checked: boolean) => setValues((current) => ({
    ...current,
    show_public_availability: checked,
    show_public_booker_names: checked ? current.show_public_booker_names : false,
  }));
  const notificationsValue = values.requester_notifications_enabled === null
    ? "inherit"
    : values.requester_notifications_enabled ? "on" : "off";

  return (
    <form className="grid gap-4" onSubmit={submit}>
      <fieldset className="grid gap-3 sm:grid-cols-2" disabled={disabled || pending}>
        <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Name
          <input className="desk-input" required maxLength={200} value={values.name} onChange={(event) => set("name", event.target.value)} />
        </label>
        <label className="grid gap-1 text-sm font-semibold text-ink">Space type
          <select className="desk-input" required value={values.kind} onChange={(event) => set("kind", event.target.value as FormValues["kind"])}>
            <option value="dev_room">Development room</option>
            <option value="bench">Bench</option>
            <option value="meeting">Meeting room</option>
            <option value="other">Other</option>
          </select>
        </label>
        {makerspaceId !== undefined ? <BookableSpaceMachineType makerspaceId={makerspaceId} value={values.machine_type ?? null} onChange={(value) => set("machine_type", value)} /> : null}
        <label className="grid gap-1 text-sm font-semibold text-ink">Capacity
          <input className="desk-input" type="number" min={0} value={values.capacity} onChange={(event) => set("capacity", Number(event.target.value))} />
          <span className="text-xs font-normal text-muted">Use 0 when no capacity is published.</span>
        </label>
        <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Location
          <input className="desk-input" maxLength={255} value={values.location} onChange={(event) => set("location", event.target.value)} />
        </label>
        <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Description
          <textarea className="desk-input min-h-24" value={values.description} onChange={(event) => set("description", event.target.value)} />
        </label>
        <label className="grid gap-1 text-sm font-semibold text-ink">Approval mode
          <select className="desk-input" value={values.approval_mode} onChange={(event) => set("approval_mode", event.target.value as FormValues["approval_mode"])}>
            <option value="instant">Instant confirmation</option>
            <option value="approve">Staff approval required</option>
          </select>
        </label>
        <label className="grid gap-1 text-sm font-semibold text-ink">Booking price
          <input className="desk-input" type="number" min="0" step="0.01" value={values.payment_amount} onChange={(event) => set("payment_amount", event.target.value)} />
          <span className="text-xs font-normal text-muted">Use 0 for no charge.</span>
        </label>
        <label className="grid gap-1 text-sm font-semibold text-ink">Requester email
          <select className="desk-input" value={notificationsValue} onChange={(event) => set("requester_notifications_enabled", event.target.value === "inherit" ? null : event.target.value === "on")}>
            <option value="inherit">Inherit makerspace setting</option>
            <option value="on">On</option>
            <option value="off">Off</option>
          </select>
        </label>
        <div className="grid gap-2 sm:col-span-2">
          <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={values.is_public} onChange={(event) => set("is_public", event.target.checked)} />Show this space on the public Bookings page</label>
          <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={values.show_public_availability} onChange={(event) => changeAvailability(event.target.checked)} />Publish confirmed booking intervals</label>
          <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={values.show_public_booker_names} disabled={!values.show_public_availability} onChange={(event) => set("show_public_booker_names", event.target.checked)} />Show booker names with published intervals</label>
        </div>
      </fieldset>
      <CustomFormBuilder value={values.custom_form as CustomFormSchema} onChange={(schema) => set("custom_form", schema)} disabled={disabled || pending} />
      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
      {!disabled ? <button className="desk-button-primary w-fit" type="submit" disabled={pending}>{pending ? "Saving..." : submitLabel}</button> : null}
    </form>
  );
}
