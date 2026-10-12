import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog } from "../../../components/ui";
import { devicesApi, type Device, type DeviceKind, type EnrollmentGrant } from "../devicesApi";
import { deviceQueryKeys } from "../deviceQueryKeys";

export function DeviceCreateForm({ makerspaceId, onGrant }: {
  makerspaceId: number; onGrant: (grant: EnrollmentGrant) => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<DeviceKind>("generic");
  const create = useMutation({
    // Return void: TanStack must never retain bearer material as mutation data.
    mutationFn: async () => {
      const response = await devicesApi.create(makerspaceId, { name, kind, offline_threshold_seconds: 300 });
      onGrant(response.enrollment);
    },
    onSuccess: () => {
      setName("");
      void client.invalidateQueries({ queryKey: deviceQueryKeys.root(makerspaceId) });
    },
  });
  return <form className="mb-4 flex flex-wrap gap-3" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
    <label>Device name<input className="desk-input block" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></label>
    <label>Device kind<select className="desk-input block" value={kind} onChange={(e) => setKind(e.target.value as DeviceKind)}>
      <option value="generic">Generic</option><option value="printer">Printer</option><option value="label_printer">Label printer</option>
    </select></label>
    <button className="desk-button" disabled={create.isPending || !name.trim()}>Create device</button>
    {create.isPending ? <p role="status">Creating device...</p> : null}
    {create.error ? <p role="alert">Could not create device. Please retry.</p> : null}
  </form>;
}

export function DeviceIdentitySection({ device, onGrant }: { device: Device; onGrant: (grant: EnrollmentGrant) => void }) {
  const client = useQueryClient();
  const [name, setName] = useState(device.name);
  const [threshold, setThreshold] = useState(device.offline_threshold_seconds);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const action = useMutation({
    mutationFn: async (operation: "save" | "enrollment" | "revoke") => {
      if (operation === "enrollment") onGrant(await devicesApi.enrollment(device.id));
      else if (operation === "revoke") await devicesApi.revoke(device.id);
      else await devicesApi.update(device.id, { name, offline_threshold_seconds: threshold });
      // Enrollment response is consumed only by local state, never returned to TanStack.
    },
    onSuccess: () => {
      setConfirmRevoke(false);
      void client.invalidateQueries({ queryKey: deviceQueryKeys.root(device.makerspace) });
    },
  });
  return <section className="mt-4 border-t border-line pt-4" aria-label={`Identity for ${device.name}`}>
    <h3 className="title-section">{device.name}</h3>
    <p>Fingerprint: {device.key_fingerprint ? `${device.key_fingerprint.slice(0, 12)}...` : "Not enrolled"} | Key version {device.key_version}</p>
    <form className="flex flex-wrap gap-3" onSubmit={(e) => { e.preventDefault(); action.mutate("save"); }}>
      <label>Name<input className="desk-input block" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Offline threshold (seconds)<input className="desk-input block" required type="number" min={1} max={604800} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} /></label>
      <button className="desk-button" disabled={action.isPending}>Save identity</button>
    </form>
    <div className="mt-3 flex gap-3">
      <button className="desk-button" disabled={action.isPending} onClick={() => action.mutate("enrollment")}>
        {device.status === "active" ? "Rotate key" : device.status === "revoked" ? "Reactivate device" : "Issue enrollment"}
      </button>
      <button className="desk-button" disabled={action.isPending || device.status === "revoked"} onClick={() => setConfirmRevoke(true)}>Revoke device</button>
    </div>
    <p role="status">{action.isPending ? "Saving..." : action.isSuccess ? "Device updated." : ""}</p>
    {action.error ? <p role="alert">Device change failed. Please retry.</p> : null}
    <ConfirmDialog open={confirmRevoke} onCancel={() => setConfirmRevoke(false)} title="Revoke device"
      onConfirm={() => action.mutate("revoke")} pending={action.isPending} tone="danger"
      message="This immediately stops signed requests from this device. Re-enrollment is required to activate it again." />
  </section>;
}
