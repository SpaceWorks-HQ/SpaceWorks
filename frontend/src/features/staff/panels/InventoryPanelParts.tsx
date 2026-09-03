import type { ReactNode } from "react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Field, Modal, StatusBadge } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { QrImage } from "./QrImage";
import { AssetEditForm } from "./AssetEditForm";
import { type Category, useStaffGet } from "./shared";
import {
  formatActor,
  formatDate,
  humanize,
  type Actor,
  type AdjustmentForm,
  type AdminProduct,
  type InventoryAssetRow,
  type ItemForm,
  type LendingHistoryResponse,
  type QrHistoryResponse,
} from "./InventoryPanelShared";

export function ItemModal({ title, open, onClose, form, setForm, categories, includeQuantities = false, pending, error, onSubmit, children }: {
  title: string; open: boolean; onClose: () => void; form: ItemForm; setForm: (updater: (current: ItemForm) => ItemForm) => void; categories: Category[];
  includeQuantities?: boolean; pending: boolean; error?: string; onSubmit: () => void; children?: ReactNode;
}) {
  return (
    <Modal open={open} onClose={onClose} title={title} footer={<div className="desk-actions flex flex-wrap justify-end gap-2"><button className="desk-button-ghost" type="button" disabled={pending} onClick={onClose}>Cancel</button><button className="desk-button-primary" type="button" disabled={pending || !form.name.trim()} onClick={onSubmit}>Save</button></div>}>
      <div className="grid gap-3 text-sm">
        <Field label="Name"><input className="desk-input" placeholder="e.g. Soldering iron" value={form.name} onChange={(e) => setForm((c) => ({ ...c, name: e.target.value }))} /></Field>
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label="Tracking mode"><select className="desk-input" value={form.tracking_mode} onChange={(e) => setForm((c) => ({ ...c, tracking_mode: e.target.value }))}><option value="quantity">Quantity</option><option value="individual">Individual</option></select></Field>
          <Field label="Category"><select className="desk-input" value={form.category} onChange={(e) => setForm((c) => ({ ...c, category: e.target.value }))}><option value="">Uncategorized</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></Field>
        </div>
        <Field label="Description"><textarea className="desk-input h-20" placeholder="Optional notes" value={form.description} onChange={(e) => setForm((c) => ({ ...c, description: e.target.value }))} /></Field>
        <Field label="Storage location"><input className="desk-input" placeholder="e.g. Shelf B3" value={form.storage_location} onChange={(e) => setForm((c) => ({ ...c, storage_location: e.target.value }))} /></Field>
        {includeQuantities ? <div className="grid gap-2 sm:grid-cols-2"><Field label="Total quantity"><input className="desk-input" type="number" min="0" value={form.total_quantity} onChange={(e) => setForm((c) => ({ ...c, total_quantity: e.target.value }))} /></Field><Field label="Available quantity"><input className="desk-input" type="number" min="0" value={form.available_quantity} onChange={(e) => setForm((c) => ({ ...c, available_quantity: e.target.value }))} /></Field></div> : null}
        <div className="grid gap-2 sm:grid-cols-3"><label className="inline-flex items-center gap-2"><input type="checkbox" checked={form.is_public} onChange={(e) => setForm((c) => ({ ...c, is_public: e.target.checked }))} /> Public</label><label className="inline-flex items-center gap-2"><input type="checkbox" checked={form.public_self_checkout_enabled} onChange={(e) => setForm((c) => ({ ...c, public_self_checkout_enabled: e.target.checked }))} /> Self checkout</label><label className="inline-flex items-center gap-2"><input type="checkbox" checked={form.show_public_count} onChange={(e) => setForm((c) => ({ ...c, show_public_count: e.target.checked }))} /> Show count</label></div>
        <Field label="Public visibility"><select className="desk-input" value={form.public_availability_mode} onChange={(e) => setForm((c) => ({ ...c, public_availability_mode: e.target.value }))}><option value="status_only">Status only</option><option value="exact_count">Exact count</option><option value="hidden">Hidden</option></select></Field>
        {includeQuantities ? <p className="text-xs text-muted">A photo can be added after saving â€” the item opens for editing so you can upload one.</p> : null}
        {children}
        {error ? <p className="text-sm text-danger">{error}</p> : null}
      </div>
    </Modal>
  );
}

export function QuantityAdjust({ product, form, setForm, pending, error, onSubmit }: { product: AdminProduct; form: AdjustmentForm; setForm: (updater: (current: AdjustmentForm) => AdjustmentForm) => void; pending: boolean; error?: string; onSubmit: () => void }) {
  return (
    <div className="grid gap-3 border-t border-line pt-3">
      <h3 className="title-section">Adjust quantities</h3>
      <div className="grid gap-2 sm:grid-cols-3"><InventoryMetric label="Available" value={product.available_quantity} /><InventoryMetric label="Damaged" value={product.damaged_quantity} /><InventoryMetric label="Lost" value={product.lost_quantity} /></div>
      <div className="grid gap-2 sm:grid-cols-3"><Field label="Â± Available"><input className="desk-input" type="number" value={form.delta_available} onChange={(e) => setForm((c) => ({ ...c, delta_available: e.target.value }))} /></Field><Field label="Â± Damaged"><input className="desk-input" type="number" value={form.delta_damaged} onChange={(e) => setForm((c) => ({ ...c, delta_damaged: e.target.value }))} /></Field><Field label="Â± Lost"><input className="desk-input" type="number" value={form.delta_lost} onChange={(e) => setForm((c) => ({ ...c, delta_lost: e.target.value }))} /></Field></div>
      <Field label="Adjustment reason"><input className="desk-input" value={form.reason} onChange={(e) => setForm((c) => ({ ...c, reason: e.target.value }))} /></Field>
      <div className="desk-actions flex justify-end"><button className="desk-button-primary" type="button" disabled={pending || !form.reason.trim()} onClick={onSubmit}>Apply adjustment</button></div>
      {error ? <p className="text-sm text-danger">{error}</p> : null}
    </div>
  );
}

export function QrHistory({ title, queryKey, path }: { title: string; queryKey: unknown[]; path: string }) {
  const [open, setOpen] = useState(false);
  const history = useStaffGet<QrHistoryResponse>(queryKey, path, open);
  const rows = history.data?.scans ?? [];
  return (
    <div className="grid w-full gap-2 border-t border-line pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="title-section">{title}</h3>
        <button className="desk-button-ghost" type="button" onClick={() => setOpen((value) => !value)}>{open ? "Hide" : "History"}</button>
      </div>
      {open && history.isLoading ? <p className="text-sm text-muted">Loading QR history...</p> : null}
      {open && history.error ? <p className="text-sm text-danger">{history.error.message}</p> : null}
      {open && !history.isLoading && !rows.length ? <p className="text-sm text-muted">No QR scans recorded.</p> : null}
      {open && rows.length ? (
        <ul className="eyebrow grid gap-1">
          {rows.map((scan) => (
            <li key={scan.id} className="rounded-md border border-line bg-surface px-2 py-1">
              <span className="font-medium text-ink">{humanize(scan.context)}</span> on {formatDate(scan.created_at)}{scan.actor ? ` by user #${scan.actor}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function IndividualAssets({ productId, makerspaceId, refreshInventory }: { productId: number; makerspaceId: number; refreshInventory: () => void }) {
  const queryClient = useQueryClient();
  const [editingAssetId, setEditingAssetId] = useState<number | null>(null);
  const assets = useStaffGet<{ results: InventoryAssetRow[] }>(["inventory-assets", productId], `/admin/inventory/${productId}/assets`);
  const containers = useStaffGet<{ results: { id: number; label: string }[] } | { id: number; label: string }[]>(
    ["containers-all", makerspaceId],
    `/admin/makerspace/${makerspaceId}/containers?page_size=1000`,
  );
  const containerOptions = Array.isArray(containers.data) ? containers.data : containers.data?.results ?? [];
  const saveAsset = () => {
    setEditingAssetId(null);
    queryClient.invalidateQueries({ queryKey: ["inventory-assets", productId] });
    refreshInventory();
  };
  const action = useMutation({
    mutationFn: ({ assetId, action }: { assetId: number; action: "shelve" | "repair" }) =>
      staffRequest(`/admin/assets/${assetId}/fix-status`, {
        method: "POST",
        body: JSON.stringify({ action }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inventory-assets", productId] });
      queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspaceId] });
      refreshInventory();
    },
  });
  const rows = assets.data?.results ?? [];
  return (
    <div className="grid gap-2 border-t border-line pt-3">
      <h3 className="title-section">Individual assets</h3>
      {assets.isLoading ? <p className="text-sm text-muted">Loading assets...</p> : null}
      {assets.error ? <p className="text-sm text-danger">{assets.error.message}</p> : null}
      {!assets.isLoading && !rows.length ? <p className="text-sm text-muted">No asset records yet.</p> : null}
      <div className="grid gap-2">
        {rows.map((asset) => (
          <div key={asset.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-surface p-2 text-sm">
            <div className="flex min-w-0 flex-1 items-center gap-3">
              {asset.qr_code_id ? <div className="w-16 shrink-0"><QrImage qrId={asset.qr_code_id} label={asset.asset_tag} /></div> : null}
              <div className="min-w-0">
                <p className="font-medium text-ink">{asset.asset_tag}</p>
                <p className="text-xs text-muted">{[asset.serial_number, asset.box_label, asset.status].filter(Boolean).join(" | ")}</p>
                <p className="truncate font-mono text-xs text-muted">{asset.qr_code_id ? `QR #${asset.qr_code_id} | ${asset.qr_payload ?? ""}` : "No QR linked"}</p>
              </div>
            </div>
            <div className="desk-actions flex flex-wrap gap-2">
              <button className="desk-button-ghost" type="button" onClick={() => setEditingAssetId((current) => (current === asset.id ? null : asset.id))}>
                {editingAssetId === asset.id ? "Close" : "Edit"}
              </button>
              <QrHistory title="Asset QR history" queryKey={["asset-qr-history", asset.id]} path={`/admin/assets/${asset.id}/qr-history`} />
              {asset.status === "maintenance" ? (
                <button className="desk-button-success" type="button" disabled={action.isPending} onClick={() => action.mutate({ assetId: asset.id, action: "repair" })}>Move back to inventory</button>
              ) : (
                <button className="desk-button-warn" type="button" disabled={action.isPending || !["available", "damaged"].includes(asset.status)} onClick={() => action.mutate({ assetId: asset.id, action: "shelve" })}>To Fix</button>
              )}
            </div>
            {editingAssetId === asset.id ? (
              <div className="w-full">
                <AssetEditForm asset={asset} containers={containerOptions} onSaved={saveAsset} onCancel={() => setEditingAssetId(null)} />
              </div>
            ) : null}
          </div>
        ))}
      </div>
      {action.error ? <p className="text-sm text-danger">{action.error.message}</p> : null}
    </div>
  );
}

export function LendingHistory({ productId }: { productId: number }) {
  const history = useStaffGet<LendingHistoryResponse>(["lending-history", productId], `/admin/inventory/${productId}/lending-history`);
  const last = history.data?.last_borrower;
  const recent = history.data?.recent ?? [];
  return (
    <div className="grid gap-2 border-t border-line pt-3">
      <h3 className="title-section">Lending history</h3>
      {history.isLoading ? <p className="text-sm text-muted">Loading lending history...</p> : null}
      {history.error ? <p className="text-sm text-danger">{history.error.message}</p> : null}
      {!history.isLoading && !history.error && !recent.length ? <p className="text-sm text-muted">No lending history yet.</p> : null}
      {last ? (
        <div className="text-sm text-ink">
          <p>Last borrower: {last.username} ({formatDate(last.issued_at)})</p>
          <AttributionLine acceptedBy={last.accepted_by} issuedBy={last.issued_by} />
        </div>
      ) : null}
      {recent.length ? (
        <ul className="grid gap-1 text-sm text-muted">
          {recent.map((entry) => (
            <li key={entry.id}>
              {entry.username} Ã¢â‚¬â€ {entry.quantity} on {formatDate(entry.issued_at)}
              <AttributionLine acceptedBy={entry.accepted_by} issuedBy={entry.issued_by} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function InventoryAvailability({ product }: { product: AdminProduct }) {
  const isLowStock = product.available_quantity <= Math.ceil(product.total_quantity * 0.2);
  const badge = product.available_quantity <= 0 ? <StatusBadge status="lost" label="Unavailable" /> : isLowStock ? <StatusBadge status="limited" label="Limited" /> : <StatusBadge status="available" label="Available" />;
  return <span className="inline-flex items-center gap-2"><span className="inline-block w-8 font-medium tabular-nums text-ink">{product.available_quantity}</span>{badge}</span>;
}

export function InventoryMetric({ label, value }: { label: string; value: number }) {
  const tones: Record<string, string> = {
    Available: "border-success bg-success/15",
    Damaged: "border-warn bg-warn/15",
    Lost: "border-secondary bg-secondary/15",
  };
  return <div className={`rounded-md border p-3 ${tones[label] ?? "border-accent bg-accent/15"}`}><p className="eyebrow">{label}</p><p className="mt-1 font-mono text-xl font-bold text-ink">{value}</p></div>;
}

export function AttributionLine({ acceptedBy, issuedBy }: { acceptedBy: Actor | null; issuedBy: Actor | null }) {
  const parts = [
    acceptedBy ? `Accepted by ${formatActor(acceptedBy)}` : "",
    issuedBy ? `Issued by ${formatActor(issuedBy)}` : "",
  ].filter(Boolean);
  return parts.length ? <p className="text-xs text-muted">{parts.join(" | ")}</p> : null;
}
