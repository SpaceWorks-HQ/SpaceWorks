import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  machineKeys,
  machineImageEndpoint,
  retireMachine,
  setMachineStatus,
  unretireMachine,
  updateMachine,
  type Machine,
  type MachineStatus,
} from "../../machinesApi";
import { ImageUploader } from "../../ImageUploader";
import { MachinePublicSettings } from "../MachinePublicSettings";

const MACHINE_STATUSES: MachineStatus[] = ["idle", "running", "reserved", "maintenance", "offline"];
type MachineForm = Pick<Machine, "name" | "location" | "notes" | "firmware_version" | "camera_feed_url">;

export function OverviewTab({ machine, makerspaceId, canManageMachines, canEdit, canOperate, canRetire, canUnretire }: {
  machine: Machine;
  makerspaceId: number;
  canManageMachines: boolean;
  canEdit: boolean;
  canOperate: boolean;
  canRetire: boolean;
  canUnretire: boolean;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<MachineForm>({
    name: "", location: "", notes: "", firmware_version: "", camera_feed_url: "",
  });
  const [status, setStatus] = useState<MachineStatus>(machine.status);

  useEffect(() => {
    setForm({
      name: machine.name,
      location: machine.location,
      notes: machine.notes,
      firmware_version: machine.firmware_version,
      camera_feed_url: machine.camera_feed_url,
    });
    setStatus(machine.status);
  }, [machine]);

  const refreshMachine = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: machineKeys.detail(machine.id) }),
      queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) }),
    ]);
  };
  const save = useMutation({
    mutationFn: () => updateMachine(machine.id, {
      name: form.name.trim(),
      location: form.location.trim(),
      notes: form.notes.trim(),
      firmware_version: form.firmware_version.trim(),
      camera_feed_url: form.camera_feed_url.trim(),
    }),
    onSuccess: refreshMachine,
  });
  const setStatusMutation = useMutation({
    mutationFn: () => setMachineStatus(machine.id, status),
    onSuccess: refreshMachine,
  });
  const lifecycle = useMutation({
    mutationFn: (action: "retire" | "unretire") =>
      action === "retire" ? retireMachine(machine.id) : unretireMachine(machine.id),
    onSuccess: refreshMachine,
  });
  const updateField = (field: keyof MachineForm, value: string) =>
    setForm((current) => ({ ...current, [field]: value }));
  const canChangeLifecycle = machine.is_active ? canRetire : canUnretire;

  return (
    <div className="grid gap-5">
      {canEdit ? (
        <section className="grid gap-3">
          <h3 className="title-section">Machine photo</h3>
          <ImageUploader
            endpoint={machineImageEndpoint(machine.id)}
            currentUrl={machine.image_url}
            label="Machine photo"
            onChanged={() => { void refreshMachine(); }}
          />
        </section>
      ) : null}
      <section className="grid gap-3">
        <h3 className="title-section">Machine details</h3>
        <label className="eyebrow grid gap-1">Name
          <input className="desk-input" value={form.name} disabled={!canEdit}
            onChange={(event) => updateField("name", event.target.value)} />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="eyebrow grid gap-1">Location
            <input className="desk-input" value={form.location} disabled={!canEdit}
              onChange={(event) => updateField("location", event.target.value)} />
          </label>
          <label className="eyebrow grid gap-1">Firmware version
            <input className="desk-input" value={form.firmware_version} disabled={!canEdit}
              onChange={(event) => updateField("firmware_version", event.target.value)} />
          </label>
        </div>
        <label className="eyebrow grid gap-1">Camera feed URL
          <input className="desk-input" type="url" value={form.camera_feed_url} disabled={!canEdit}
            onChange={(event) => updateField("camera_feed_url", event.target.value)} />
        </label>
        <label className="eyebrow grid gap-1">Notes
          <textarea className="desk-input min-h-24" value={form.notes} disabled={!canEdit}
            onChange={(event) => updateField("notes", event.target.value)} />
        </label>
        <button className="desk-button-primary justify-self-start" type="button"
          disabled={!canEdit || save.isPending || !form.name.trim()} onClick={() => save.mutate()}>
          {save.isPending ? "Saving..." : "Save changes"}
        </button>
        {save.error instanceof Error ? <p className="text-sm text-danger">{save.error.message}</p> : null}
      </section>
      <section className="border-t border-line pt-4">
        <h3 className="title-section mb-3">Status</h3>
        <div className="flex flex-col gap-2 sm:flex-row">
          <select className="desk-input flex-1" aria-label="Machine status" value={status} disabled={!canOperate}
            onChange={(event) => setStatus(event.target.value as MachineStatus)}>
            {MACHINE_STATUSES.map((value) => (
              <option key={value} value={value}>{value.replace("_", " ")}</option>
            ))}
          </select>
          <button className="desk-button-primary" type="button"
            disabled={!canOperate || setStatusMutation.isPending} onClick={() => setStatusMutation.mutate()}>
            {setStatusMutation.isPending ? "Setting..." : "Set status"}
          </button>
          <button className={machine.is_active ? "desk-button-danger" : "desk-button-success"} type="button" disabled={!canChangeLifecycle || lifecycle.isPending}
            onClick={() => lifecycle.mutate(machine.is_active ? "retire" : "unretire")}>
            {machine.is_active ? "Retire" : "Reactivate"}
          </button>
        </div>
        {setStatusMutation.error instanceof Error ? <p className="mt-2 text-sm text-danger">{setStatusMutation.error.message}</p> : null}
        {lifecycle.error instanceof Error ? <p className="mt-2 text-sm text-danger">{lifecycle.error.message}</p> : null}
      </section>
      {canManageMachines ? (
        <MachinePublicSettings machine={machine} makerspaceId={makerspaceId} />
      ) : null}
    </div>
  );
}
