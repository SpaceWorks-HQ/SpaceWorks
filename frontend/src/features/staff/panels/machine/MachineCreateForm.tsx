import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../../../lib/api";
import { ImageUploader } from "../../ImageUploader";
import {
  createMachine,
  isBuiltinPrinterType,
  machineImageEndpoint,
  machineKeys,
  type Machine,
  type MachineType,
} from "../../machinesApi";

type Props = {
  makerspaceId: number;
  machineType: MachineType;
  onCreated: (machineId: number) => void;
};

type WarrantyForm = {
  purchased_on: string;
  warranty_expires_on: string;
  vendor_name: string;
  vendor_contact: string;
};

const emptyWarranty: WarrantyForm = {
  purchased_on: "",
  warranty_expires_on: "",
  vendor_name: "",
  vendor_contact: "",
};
const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export function MachineCreateForm({ makerspaceId, machineType, onCreated }: Props) {
  const queryClient = useQueryClient();
  const confirmationRef = useRef<HTMLParagraphElement>(null);
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [location, setLocation] = useState("");
  const [createdMachine, setCreatedMachine] = useState<Machine | null>(null);
  const [warrantyForm, setWarrantyForm] = useState<WarrantyForm>(emptyWarranty);
  const wantsModel = isBuiltinPrinterType(machineType);

  const create = useMutation({
    mutationFn: () => createMachine(makerspaceId, {
      name: name.trim(),
      machine_type_id: machineType.id,
      location: location.trim(),
      notes: "",
      firmware_version: "",
      camera_feed_url: "",
      ...(wantsModel && model.trim() ? { type_payload: { model: model.trim() } } : {}),
    }),
    onSuccess: async (machine) => {
      setCreatedMachine(machine);
      onCreated(machine.id);
      await queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) });
    },
  });

  const warranty = useMutation({
    mutationFn: () => {
      if (!createdMachine) throw new Error("Create the machine before adding warranty details.");
      const payload = Object.fromEntries(
        Object.entries(warrantyForm).filter(([, value]) => value.trim()),
      );
      return staffRequest(`/admin/machines/${createdMachine.id}/warranty`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    },
  });

  useEffect(() => {
    if (createdMachine) confirmationRef.current?.focus();
  }, [createdMachine]);

  const updateWarranty = (field: keyof WarrantyForm, value: string) => {
    warranty.reset();
    setWarrantyForm((current) => ({ ...current, [field]: value }));
  };
  const hasWarrantyDetails = Object.values(warrantyForm).some((value) => value.trim());

  const finish = () => {
    setName("");
    setModel("");
    setLocation("");
    setWarrantyForm(emptyWarranty);
    setCreatedMachine(null);
    create.reset();
    warranty.reset();
  };

  const refreshMachine = async () => {
    if (!createdMachine) return;
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: machineKeys.detail(createdMachine.id) }),
      queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) }),
    ]);
  };

  return (
    <section className="grid gap-4 border-b border-line p-3" aria-labelledby={`add-machine-${machineType.id}`}>
      <form
        className="grid gap-3 sm:grid-cols-2 sm:items-end"
        onSubmit={(event) => { event.preventDefault(); create.mutate(); }}
      >
        <h3 className="title-section sm:col-span-2" id={`add-machine-${machineType.id}`}>
          Add {machineType.name}
        </h3>
        <label className="sr-only" htmlFor={`machine-name-${machineType.id}`}>Machine name</label>
        <label className="eyebrow grid gap-1" htmlFor={`machine-name-${machineType.id}`}>
          Name
          <input
            id={`machine-name-${machineType.id}`}
            className={`desk-input min-h-11 ${focusRing}`}
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            disabled={!!createdMachine}
          />
        </label>
        {wantsModel ? (
          <>
            <label className="sr-only" htmlFor={`machine-model-${machineType.id}`}>Printer model</label>
            <label className="eyebrow grid gap-1" htmlFor={`machine-model-${machineType.id}`}>
              Make and model
              <input
                id={`machine-model-${machineType.id}`}
                className={`desk-input min-h-11 ${focusRing}`}
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="e.g. Prusa MK4"
                disabled={!!createdMachine}
              />
            </label>
          </>
        ) : null}
        <label className="eyebrow grid gap-1">
          Location
          <input
            className={`desk-input min-h-11 ${focusRing}`}
            value={location}
            onChange={(event) => setLocation(event.target.value)}
            disabled={!!createdMachine}
          />
        </label>
        <button
          className={`desk-button-primary min-h-11 ${focusRing}`}
          type="submit"
          disabled={create.isPending || !name.trim() || !!createdMachine}
        >
          {create.isPending ? `Adding ${machineType.name}...` : createdMachine ? "Machine created" : `Add ${machineType.name}`}
        </button>
        {create.error instanceof Error ? (
          <p className="text-sm text-danger sm:col-span-2">{create.error.message}</p>
        ) : null}
      </form>

      {createdMachine ? (
        <div className="grid gap-5 border-t border-line pt-4">
          <p
            ref={confirmationRef}
            tabIndex={-1}
            role="status"
            className={`rounded-lg bg-success px-3 py-2 text-on-success ${focusRing}`}
          >
            {createdMachine.name} was created. Photo and warranty details are optional.
          </p>

          <section className="grid gap-3">
            <h3 className="title-section">Machine photo</h3>
            <ImageUploader
              endpoint={machineImageEndpoint(createdMachine.id)}
              currentUrl={createdMachine.image_url}
              label="Machine photo"
              onChanged={() => { void refreshMachine(); }}
            />
          </section>

          <form
            className="grid gap-3"
            aria-labelledby={`machine-warranty-${createdMachine.id}`}
            onSubmit={(event) => { event.preventDefault(); warranty.mutate(); }}
          >
            <h3 className="title-section" id={`machine-warranty-${createdMachine.id}`}>Warranty</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <WarrantyField label="Purchased on" type="date" value={warrantyForm.purchased_on}
                onChange={(value) => updateWarranty("purchased_on", value)} />
              <WarrantyField label="Warranty expires on" type="date" value={warrantyForm.warranty_expires_on}
                onChange={(value) => updateWarranty("warranty_expires_on", value)} />
              <WarrantyField label="Vendor name" value={warrantyForm.vendor_name} maxLength={200}
                onChange={(value) => updateWarranty("vendor_name", value)} />
              <WarrantyField label="Vendor contact" value={warrantyForm.vendor_contact} maxLength={200}
                onChange={(value) => updateWarranty("vendor_contact", value)} />
            </div>
            <button className={`desk-button-secondary min-h-11 justify-self-start ${focusRing}`} type="submit"
              disabled={warranty.isPending || !hasWarrantyDetails}>
              {warranty.isPending ? "Saving warranty..." : "Save warranty"}
            </button>
            {warranty.isSuccess ? <p className="text-sm text-success-ink">Warranty details saved.</p> : null}
            {warranty.error instanceof Error ? (
              <p className="text-sm text-danger" role="alert">
                {createdMachine.name} is still created. Warranty details were not saved: {warranty.error.message}
              </p>
            ) : null}
          </form>

          <button className={`desk-button-success min-h-11 justify-self-start ${focusRing}`} type="button" onClick={finish}>
            Done
          </button>
        </div>
      ) : null}
    </section>
  );
}

function WarrantyField({ label, value, onChange, type = "text", maxLength }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "date";
  maxLength?: number;
}) {
  return (
    <label className="eyebrow grid gap-1">
      {label}
      <input className={`desk-input min-h-11 ${focusRing}`} type={type} value={value} maxLength={maxLength}
        onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}
