import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../../lib/api";
import { WarrantySection } from "../WarrantySection";
import { invalidateContainerViews } from "../queryInvalidation";
import { Panel, type Makerspace, useStaffGet } from "./shared";
import { QrImage } from "./QrImage";

type Container = { id: number; code?: string; label: string; location?: string; is_active?: boolean };
type Contents = {
  products: { id: number; name: string; available_quantity: number; tracking_mode: string }[];
  assets: { id: number; asset_tag: string; product: string; status: string }[];
  children: Container[];
};
type History = { scans: { id: string; source: string; context: string; actor: number | null; created_at: string }[] };

// Containers had list + create (in QR tools) but no edit/move/contents/history surface in
// React - they were only manageable in the Django admin. This panel wires the operations
// container endpoints (MANAGE_QR for edit/move, VIEW_INVENTORY for contents/history).
export function ContainersPanel({ makerspace, canEditInventory }: { makerspace: Makerspace; canEditInventory: boolean }) {
  const containers = useStaffGet<{ results: Container[] }>(["containers", makerspace.id], `/admin/makerspace/${makerspace.id}/containers?page_size=1000`);
  return (
    <Panel title="Containers">
      {containers.isLoading ? <p className="text-sm text-muted">Loading containers...</p> : null}
      {containers.error instanceof Error ? <p className="text-sm text-danger">{containers.error.message}</p> : null}
      <div className="grid gap-2">
        {containers.data?.results?.map((container) => (
          <ContainerRow key={container.id} container={container} makerspaceId={makerspace.id} canEditInventory={canEditInventory} />
        ))}
        {!containers.isLoading && !containers.error && !containers.data?.results?.length ? (
          <p className="text-sm text-muted">No containers yet. Create one in QR tools.</p>
        ) : null}
      </div>
    </Panel>
  );
}

function ContainerRow({ container, makerspaceId, canEditInventory }: { container: Container; makerspaceId: number; canEditInventory: boolean }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [panel, setPanel] = useState<"contents" | "history" | null>(null);
  const [label, setLabel] = useState(container.label);
  const [location, setLocation] = useState(container.location ?? "");
  const [isActive, setIsActive] = useState(container.is_active ?? true);

  const contents = useStaffGet<Contents>(["container-contents", container.id], `/admin/containers/${container.id}/contents`, panel === "contents");
  const history = useStaffGet<History>(["container-history", container.id], `/admin/containers/${container.id}/history`, panel === "history");

  const save = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/containers/${container.id}/move`, {
        method: "POST",
        body: JSON.stringify({ label: label.trim(), location: location.trim(), is_active: isActive }),
      }),
    onSuccess: () => {
      setEditing(false);
      invalidateContainerViews(queryClient, makerspaceId, container.id);
    },
  });
  const saveError = save.error instanceof Error ? save.error.message : undefined;
  const togglePanel = (next: "contents" | "history") => setPanel((current) => (current === next ? null : next));

  return (
    <div className="min-w-0 rounded-md border border-line bg-surface p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="min-w-0 break-words text-ink">{container.label}</strong>
        {container.location ? <span className="text-xs text-muted">{container.location}</span> : null}
        {container.is_active === false ? <span className="rounded-md bg-warn/15 px-2 py-0.5 text-xs text-warn-ink">Inactive</span> : null}
        <div className="desk-actions ml-0 flex w-full flex-wrap gap-2 sm:ml-auto sm:w-auto">
          <button className="desk-button-ghost" type="button" onClick={() => setEditing((value) => !value)}>{editing ? "Cancel" : "Edit"}</button>
          <button className="desk-button-ghost" type="button" onClick={() => togglePanel("contents")}>{panel === "contents" ? "Hide contents" : "Contents"}</button>
          <button className="desk-button-ghost" type="button" onClick={() => togglePanel("history")}>{panel === "history" ? "Hide history" : "History"}</button>
        </div>
      </div>

      {editing ? (
        <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] md:items-end">
          <label className="eyebrow grid min-w-0 gap-1"><span>Label</span><input className="desk-input min-w-0" value={label} onChange={(event) => setLabel(event.target.value)} /></label>
          <label className="eyebrow grid min-w-0 gap-1"><span>Location</span><input className="desk-input min-w-0" value={location} onChange={(event) => setLocation(event.target.value)} /></label>
          <label className="eyebrow flex items-center gap-2"><input type="checkbox" checked={isActive} onChange={(event) => setIsActive(event.target.checked)} /> Active</label>
          <button className="desk-button-primary" disabled={!label.trim() || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving..." : "Save"}</button>
        </div>
      ) : null}
      {saveError ? <p className="mt-2 text-danger">{saveError}</p> : null}

      {panel === "contents" ? (
        <div className="mt-3 grid gap-2 rounded-md border border-line bg-bg p-2">
          {contents.isLoading ? <p className="text-xs text-muted">Loading...</p> : null}
          <h4 className="title-section">Products</h4>
          {contents.error instanceof Error ? <p className="text-xs text-danger">{contents.error.message}</p> : null}
          {!contents.isLoading && !contents.error && contents.data?.products.length ? contents.data.products.map((product) => (
            <p key={product.id} className="text-xs text-muted">{product.name} - {product.available_quantity} available</p>
          )) : !contents.isLoading && !contents.error ? <p className="text-xs text-muted">None</p> : null}
          <h4 className="title-section mt-1">Asset units</h4>
          {!contents.isLoading && !contents.error && contents.data?.assets.length ? contents.data.assets.map((asset) => (
            <AssetQrRow key={asset.id} asset={asset} canEditInventory={canEditInventory} />
          )) : !contents.isLoading && !contents.error ? <p className="text-xs text-muted">None</p> : null}
          {contents.data?.children.length ? (
            <p className="mt-1 text-xs text-muted">Sub-containers: {contents.data.children.map((child) => child.label).join(", ")}</p>
          ) : null}
        </div>
      ) : null}

      {panel === "history" ? (
        <div className="mt-3 rounded-md border border-line bg-bg p-2">
          {history.isLoading ? <p className="text-xs text-muted">Loading...</p> : null}
          {history.error instanceof Error ? <p className="text-xs text-danger">{history.error.message}</p> : null}
          {!history.isLoading && !history.error && history.data?.scans.length ? history.data.scans.map((scan) => (
            <p key={scan.id} className="font-mono text-xs text-muted">{new Date(scan.created_at).toLocaleString()} - {scan.context || "scan"} - {scan.source === "box_scan" ? "reviewed handover" : "QR scan"}</p>
          )) : !history.isLoading && !history.error ? <p className="text-xs text-muted">No scan history.</p> : null}
        </div>
      ) : null}
    </div>
  );
}

// Reprint a single unit's QR without rebuilding a whole batch: POST asset/<id>/qr is a
// get_or_create, so it returns the existing active QR (or makes one) and we render it.
function AssetQrRow({ asset, canEditInventory }: { asset: { id: number; asset_tag: string; product: string; status: string }; canEditInventory: boolean }) {
  const [qrId, setQrId] = useState<number | null>(null);
  const [showWarranty, setShowWarranty] = useState(false);
  const show = useMutation({
    mutationFn: () => staffRequest<{ id: number }>(`/admin/assets/${asset.id}/qr`, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: (qr) => setQrId(qr.id),
  });
  return (
    <div className="min-w-0 rounded-md border border-line bg-surface p-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <span className="min-w-0 break-words">{asset.asset_tag} ({asset.status})</span>
        <button type="button" className="desk-button-ghost" disabled={show.isPending} onClick={() => show.mutate()}>{qrId ? "QR shown" : "Show QR"}</button>
        <button type="button" className="desk-button-ghost" onClick={() => setShowWarranty((value) => !value)}>
          {showWarranty ? "Hide warranty" : "Warranty"}
        </button>
        {qrId ? <QrImage qrId={qrId} label={asset.asset_tag} /> : null}
        {show.error instanceof Error ? <span className="text-danger">{show.error.message}</span> : null}
      </div>
      {showWarranty ? <div className="mt-2"><WarrantySection hostKind="asset" hostId={asset.id} disabled={!canEditInventory} /></div> : null}
    </div>
  );
}
