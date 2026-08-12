import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { staffRequest } from "../../../lib/api";

type AssetEditRow = {
  id: number;
  asset_tag: string;
  serial_number: string;
  status: string;
  box: number | null;
  notes: string;
  public_self_checkout_enabled: boolean;
};

type ContainerOption = { id: number; label: string };

const LOCKED_STATUSES = ["issued", "reserved"];

export function AssetEditForm({
  asset,
  containers,
  onSaved,
  onCancel,
}: {
  asset: AssetEditRow;
  containers: ContainerOption[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [assetTag, setAssetTag] = useState(asset.asset_tag);
  const [serial, setSerial] = useState(asset.serial_number);
  const [boxId, setBoxId] = useState(asset.box ? String(asset.box) : "");
  const [notes, setNotes] = useState(asset.notes ?? "");
  const [publicEnabled, setPublicEnabled] = useState(asset.public_self_checkout_enabled);
  const locked = LOCKED_STATUSES.includes(asset.status);

  const save = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/assets/${asset.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          asset_tag: assetTag.trim(),
          serial_number: serial.trim(),
          box: boxId ? Number(boxId) : null,
          notes: notes.trim(),
          public_self_checkout_enabled: publicEnabled,
        }),
      }),
    onSuccess: onSaved,
  });

  if (locked) {
    return (
      <p className="mt-2 text-xs text-warn-ink">
        This asset is currently {asset.status}; finish its loan before editing its details.
      </p>
    );
  }

  return (
    <form
      className="mt-2 grid gap-2 rounded-md border border-line bg-bg p-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (assetTag.trim()) save.mutate();
      }}
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="eyebrow grid gap-1">
          <span>Asset tag</span>
          <input className="desk-input" value={assetTag} onChange={(e) => setAssetTag(e.target.value)} required />
        </label>
        <label className="eyebrow grid gap-1">
          <span>Serial number</span>
          <input className="desk-input" value={serial} onChange={(e) => setSerial(e.target.value)} />
        </label>
      </div>
      <label className="eyebrow grid gap-1">
        <span>Container</span>
        <select className="desk-input" value={boxId} onChange={(e) => setBoxId(e.target.value)}>
          <option value="">No container</option>
          {containers.map((container) => (
            <option key={container.id} value={container.id}>{container.label}</option>
          ))}
        </select>
      </label>
      <label className="eyebrow grid gap-1">
        <span>Notes</span>
        <textarea className="desk-input min-h-16 w-full" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <label className="eyebrow flex items-center gap-2">
        <input type="checkbox" checked={publicEnabled} onChange={(e) => setPublicEnabled(e.target.checked)} />
        <span>Enabled for public self-checkout</span>
      </label>
      {save.error ? <p className="text-xs text-danger">{save.error.message}</p> : null}
      <div className="desk-actions flex flex-wrap justify-end gap-2">
        <button className="desk-button-ghost" type="button" disabled={save.isPending} onClick={onCancel}>Cancel</button>
        <button className="desk-button-primary" type="submit" disabled={save.isPending || !assetTag.trim()}>
          {save.isPending ? "Saving..." : "Save"}
        </button>
      </div>
    </form>
  );
}
