import type { Key, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog, DataTable, Field, FilterBar, Modal, StatusBadge } from "../../../components/ui";
import type { DataTableColumn } from "../../../components/ui";
import { downloadStaffFile, staffRequest } from "../../../lib/api";
import { useDebouncedValue } from "../../../lib/useDebouncedValue";
import { readStorage, writeStorage } from "../../../lib/safeStorage";
import { ImageUploader } from "../ImageUploader";
import { QrImage } from "./QrImage";
import { AssetEditForm } from "./AssetEditForm";
import { ChainOfCustodyBlock } from "./LoanTimeline";
import { invalidateInventoryViews } from "../queryInvalidation";
import { categoryResults, Panel, type Category, type CategoryListResponse, type Makerspace, type Product, useStaffGet } from "./shared";

type AdminProduct = Product & {
  reserved_quantity: number;
  needs_fix_quantity: number;
  storage_location: string;
  show_public_count: boolean;
  public_availability_mode: string;
  is_archived: boolean;
};
type ItemForm = {
  name: string; tracking_mode: string; category: string; description: string; total_quantity: string; available_quantity: string;
  storage_location: string; is_public: boolean; public_self_checkout_enabled: boolean; show_public_count: boolean; public_availability_mode: string;
};
type AdjustmentForm = { delta_available: string; delta_damaged: string; delta_lost: string; reason: string };
type InventoryAssetRow = { id: number; asset_tag: string; serial_number: string; status: string; box: number | null; box_label: string | null; qr_code_id: number | null; qr_payload: string | null; notes: string; public_self_checkout_enabled: boolean };
type Actor = { username: string; role: string };
type LendingHistoryEntry = { id: number; username: string; issued_at: string; quantity: number; accepted_by: Actor | null; issued_by: Actor | null };
type LendingHistoryResponse = { product_id: number; last_borrower: LendingHistoryEntry | null; recent: LendingHistoryEntry[] };
type QrHistoryEntry = { id: string; source: string; context: string; actor: number | null; created_at: string };
type QrHistoryResponse = { product?: number; asset?: number; scans: QrHistoryEntry[] };

const emptyForm: ItemForm = {
  name: "", tracking_mode: "quantity", category: "", description: "", total_quantity: "1", available_quantity: "1",
  storage_location: "", is_public: true, public_self_checkout_enabled: false, show_public_count: false, public_availability_mode: "status_only",
};
const emptyAdjust: AdjustmentForm = { delta_available: "0", delta_damaged: "0", delta_lost: "0", reason: "" };

export function Inventory({ makerspace, canViewAudit = false, canUseToBuy = false }: { makerspace: Makerspace; canViewAudit?: boolean; canUseToBuy?: boolean }) {
  const queryClient = useQueryClient();
  const storageKey = `inventory.view.${makerspace.id}`;
  const [search, setSearch] = useState(() => readStorage(storageKey));
  const [selectedIds, setSelectedIds] = useState<Key[]>([]);
  const [form, setForm] = useState<ItemForm>(emptyForm);
  const [adjustForm, setAdjustForm] = useState<AdjustmentForm>(emptyAdjust);
  const [editing, setEditing] = useState<AdminProduct | null>(null);
  const [toBuyTarget, setToBuyTarget] = useState<AdminProduct | null>(null);
  const [toBuyQty, setToBuyQty] = useState("1");
  const [toBuyMessage, setToBuyMessage] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<AdminProduct | null>(null);
  const [fixTarget, setFixTarget] = useState<AdminProduct | null>(null);
  const [assetFixTarget, setAssetFixTarget] = useState<AdminProduct | null>(null);
  const [fixQty, setFixQty] = useState("1");
  const [qrConfirm, setQrConfirm] = useState<boolean | null>(null);
  const [bulkQrMessage, setBulkQrMessage] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [showLowStock, setShowLowStock] = useState(false);
  const debouncedSearch = useDebouncedValue(search);
  useEffect(() => {
    setSearch(readStorage(`inventory.view.${makerspace.id}`));
    setSelectedIds([]);
    setForm(emptyForm);
    setAdjustForm(emptyAdjust);
    setEditing(null);
    setToBuyTarget(null);
    setToBuyQty("1");
    setToBuyMessage("");
    setAddOpen(false);
    setArchiveTarget(null);
    setFixTarget(null);
    setAssetFixTarget(null);
    setFixQty("1");
    setQrConfirm(null);
    setBulkQrMessage("");
    setShowArchived(false);
    setShowLowStock(false);
  }, [makerspace.id]);
  const lowStockParam = showLowStock ? "&low_stock=true" : "";
  const inventoryQuery = `/admin/makerspace/${makerspace.id}/inventory?page_size=1000&archived=${showArchived ? "true" : "false"}&q=${encodeURIComponent(debouncedSearch)}${lowStockParam}`;
  const products = useStaffGet<{ results: AdminProduct[] }>(["inventory", makerspace.id, showArchived ? "archived" : "active", showLowStock ? "low" : "all", debouncedSearch], inventoryQuery);
  const categories = useStaffGet<CategoryListResponse>(["categories", makerspace.id], `/admin/makerspace/${makerspace.id}/categories`);
  const invalidate = () => {
    invalidateInventoryViews(queryClient, makerspace.id, makerspace.slug);
    queryClient.invalidateQueries({ queryKey: ["categories", makerspace.id] });
  };
  const create = useMutation({
    mutationFn: () => staffRequest<AdminProduct>(`/admin/makerspace/${makerspace.id}/inventory`, { method: "POST", body: JSON.stringify(payloadFromForm(form, true)) }),
    // Reopen the just-created item in the edit modal so the user can add a photo.
    // The image uploader needs an existing product id, so it can't live on the add
    // form - this hands off straight into editing instead of forcing a manual re-open.
    onSuccess: (created) => { setAddOpen(false); invalidate(); openEdit(created); },
  });
  const update = useMutation({
    mutationFn: () => editing ? staffRequest(`/admin/inventory/${editing.id}`, { method: "PATCH", body: JSON.stringify(payloadFromForm(form, false)) }) : Promise.resolve(),
    onSuccess: () => { setEditing(null); setAdjustForm(emptyAdjust); invalidate(); },
  });
  const adjust = useMutation({
    mutationFn: () => editing ? staffRequest(`/admin/inventory/${editing.id}/adjust-quantity`, { method: "POST", body: JSON.stringify(adjustPayload(adjustForm)) }) : Promise.resolve(),
    onSuccess: () => { setAdjustForm(emptyAdjust); invalidate(); },
  });
  const archive = useMutation({
    mutationFn: (product: AdminProduct) => staffRequest(`/admin/inventory/${product.id}`, { method: "PATCH", body: JSON.stringify({ is_archived: true }) }),
    onSuccess: () => { setArchiveTarget(null); invalidate(); },
  });
  const unarchive = useMutation({
    mutationFn: (product: AdminProduct) => staffRequest(`/admin/inventory/${product.id}`, { method: "PATCH", body: JSON.stringify({ is_archived: false }) }),
    onSuccess: () => invalidate(),
  });
  const moveToFix = useMutation({
    mutationFn: () => {
      if (!fixTarget) return Promise.reject(new Error("Select an item first."));
      return staffRequest(`/admin/inventory/${fixTarget.id}/needs-fix`, {
        method: "POST",
        body: JSON.stringify({ action: "shelve", quantity: Number(fixQty) || 1 }),
      });
    },
    onSuccess: () => {
      setFixTarget(null);
      setFixQty("1");
      queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspace.id] });
      invalidate();
    },
  });
  const bulkQr = useMutation({
    mutationFn: async (enabled: boolean) => {
      const ids = [...selectedIds];
      const results = await Promise.allSettled(
        ids.map((id) =>
          staffRequest(`/admin/inventory/${String(id)}`, {
            method: "PATCH",
            body: JSON.stringify({ public_self_checkout_enabled: enabled }),
          }),
        ),
      );
      return {
        total: ids.length,
        succeeded: results.filter((result) => result.status === "fulfilled").length,
        failed: results.filter((result) => result.status === "rejected").length,
      };
    },
    onSuccess: (result) => {
      setQrConfirm(null);
      setBulkQrMessage(`${result.succeeded} of ${result.total} items updated. ${result.failed} failed.`);
      invalidate();
    },
  });
  // Export the current view: selected rows when any are checked, else every row
  // matching the active filters (archived/search/low-stock).
  const exportInventory = useMutation({
    mutationFn: (format: "csv" | "xlsx") => {
      const base = `/admin/makerspace/${makerspace.id}/inventory/export?format=${format}`;
      const query = selectedIds.length
        ? `${base}&ids=${selectedIds.map((id) => String(id)).join(",")}`
        : `${base}&archived=${showArchived ? "true" : "false"}&q=${encodeURIComponent(debouncedSearch)}${lowStockParam}`;
      return downloadStaffFile(query, `inventory-${makerspace.slug}.${format}`);
    },
  });
  const openFix = (product: AdminProduct) => {
    if (product.tracking_mode === "individual") {
      setAssetFixTarget(product);
      return;
    }
    setFixTarget(product);
    setFixQty(product.available_quantity > 0 ? "1" : "0");
  };
  const openToBuy = (product: AdminProduct) => {
    setToBuyTarget(product);
    setToBuyQty(defaultToBuyQuantity(product));
    setToBuyMessage("");
  };
  const toBuy = useMutation({
    mutationFn: () => {
      if (!toBuyTarget) {
        return Promise.reject(new Error("Select an item first."));
      }
      return staffRequest(`/procurement/makerspace/${makerspace.id}/to-buy`, {
        method: "POST",
        body: JSON.stringify({ name: toBuyTarget.name, quantity: Number(toBuyQty) || 1, link: "", estimated_unit_cost: "" }),
      });
    },
    onSuccess: () => {
      setToBuyMessage(toBuyTarget ? `${toBuyTarget.name} added to To Buy.` : "Item added to To Buy.");
      setToBuyTarget(null);
      setToBuyQty("1");
      queryClient.invalidateQueries({ queryKey: ["procurement", makerspace.id] });
    },
  });
  const rows = useMemo(() => products.data?.results ?? [], [products.data?.results]);
  const categoryRows = categoryResults(categories.data);
  const openEdit = (product: AdminProduct) => {
    setEditing(product);
    setForm(formFromProduct(product));
    setAdjustForm(emptyAdjust);
  };
  const columns: DataTableColumn<AdminProduct>[] = [
    { key: "image", header: "", render: (product) => (
      <div className="h-10 w-10 overflow-hidden rounded-lg border border-line bg-surface">
        {product.image_url ? <img src={product.image_url} alt="" className="h-full w-full object-cover" /> : <div className="blueprint-bg h-full w-full" />}
      </div>
    ) },
    { key: "name", header: "Name", sortable: true, render: (product) => <button type="button" className="desk-button-ghost justify-start text-left" onClick={() => openEdit(product)}>{product.name}</button> },
    { key: "tracking_mode", header: "Mode", sortable: true, render: (product) => <span className="inline-flex items-center gap-2"><span>{product.tracking_mode}</span>{product.is_archived ? <StatusBadge status="archived" label="Archived" /> : null}</span> },
    { key: "total_quantity", header: "Total", sortable: true },
    { key: "available_quantity", header: "Available", sortable: true, render: (product) => <InventoryAvailability product={product} /> },
    { key: "issued_quantity", header: "Issued", sortable: true },
    { key: "damaged_quantity", header: "Damaged", sortable: true },
    { key: "lost_quantity", header: "Lost", sortable: true },
    { key: "actions", header: "", render: (product) => (
      <div className="desk-actions ml-auto grid w-max grid-cols-2 gap-2">
        <button className="desk-button-primary w-full" type="button" onClick={() => openEdit(product)}>Edit</button>
        {!product.is_archived ? <button className="desk-button-warn w-full" type="button" disabled={product.tracking_mode === "individual" ? product.available_quantity + product.damaged_quantity <= 0 : product.available_quantity <= 0} onClick={() => openFix(product)}>To Fix</button> : null}
        {product.is_archived ? <button className="desk-button-success w-full" type="button" disabled={unarchive.isPending} onClick={() => unarchive.mutate(product)}>Back to inventory</button> : <button className="desk-button-danger w-full" type="button" onClick={() => setArchiveTarget(product)}>Archive</button>}
        {canUseToBuy ? <button className="desk-button-primary w-full" type="button" onClick={() => openToBuy(product)}>To Buy</button> : null}
      </div>
    ) },
  ];
  return (
    <Panel title="Inventory">
      <div className="grid gap-3">
        <FilterBar
          value={search}
          onChange={setSearch}
          placeholder="Filter table"
          actions={(
            <>
              <button className="desk-button-primary" type="button" onClick={() => { setForm(emptyForm); setAddOpen(true); }}>Add item</button>
              <button className="desk-button-ghost" type="button" onClick={() => setShowArchived((value) => !value)}>{showArchived ? "Show active" : "Show archived"}</button>
              <button className="desk-button-ghost" type="button" onClick={() => setShowLowStock((value) => !value)}>{showLowStock ? "All stock" : "Low stock"}</button>
              <button className="desk-button-ghost" type="button" onClick={() => writeStorage(storageKey, search)}>Save view</button>
              <button className="desk-button-success" type="button" disabled={!selectedIds.length || bulkQr.isPending} onClick={() => { setBulkQrMessage(""); setQrConfirm(true); }}>Enable QR</button>
              <button className="desk-button-danger" type="button" disabled={!selectedIds.length || bulkQr.isPending} onClick={() => { setBulkQrMessage(""); setQrConfirm(false); }}>Disable QR</button>
              <button className="desk-button-ghost" type="button" disabled={exportInventory.isPending} onClick={() => exportInventory.mutate("csv")}>{selectedIds.length ? `Export CSV (${selectedIds.length})` : "Export CSV"}</button>
              <button className="desk-button-ghost" type="button" disabled={exportInventory.isPending} onClick={() => exportInventory.mutate("xlsx")}>{selectedIds.length ? `Export XLSX (${selectedIds.length})` : "Export XLSX"}</button>
            </>
          )}
        />
        <DataTable<AdminProduct> columns={columns} data={rows} getRowId={(row) => row.id} selectedIds={selectedIds} onSelectionChange={setSelectedIds} loading={products.isLoading} emptyTitle={showArchived ? "No archived inventory" : "No active inventory"} skeletonCols={columns.length + 1} />
        {toBuyMessage ? <p className="text-sm text-muted">{toBuyMessage}</p> : null}
        {bulkQrMessage ? <p className="text-sm text-muted">{bulkQrMessage}</p> : null}
        {exportInventory.error ? <p className="text-sm text-danger">{exportInventory.error instanceof Error ? exportInventory.error.message : "Could not export inventory."}</p> : null}
      </div>
      <ItemModal title="Add item" open={addOpen} onClose={() => setAddOpen(false)} form={form} setForm={setForm} categories={categoryRows} includeQuantities pending={create.isPending} error={create.error?.message} onSubmit={() => create.mutate()} />
      <ItemModal title={editing?.name ?? "Edit item"} open={Boolean(editing)} onClose={() => setEditing(null)} form={form} setForm={setForm} categories={categoryRows} pending={update.isPending} error={update.error?.message} onSubmit={() => update.mutate()}>
        {editing ? <div className="border-t border-line pt-3"><ImageUploader endpoint={`/admin/inventory/${editing.id}/image`} currentUrl={editing.image_url} label="Item photo" onChanged={invalidate} /></div> : null}
        {editing ? <QuantityAdjust product={editing} form={adjustForm} setForm={setAdjustForm} pending={adjust.isPending} error={adjust.error?.message} onSubmit={() => adjust.mutate()} /> : null}
        {editing ? <QrHistory title="Product QR history" queryKey={["product-qr-history", editing.id]} path={`/admin/inventory/${editing.id}/qr-history`} /> : null}
        {editing?.tracking_mode === "individual" ? <IndividualAssets productId={editing.id} makerspaceId={makerspace.id} refreshInventory={invalidate} /> : null}
        {editing && canViewAudit ? <LendingHistory productId={editing.id} /> : null}
        {editing && canViewAudit ? <ChainOfCustodyBlock productId={editing.id} /> : null}
      </ItemModal>
      {canUseToBuy ? (
        <Modal open={Boolean(toBuyTarget)} onClose={() => setToBuyTarget(null)} title="Add to To Buy" footer={<div className="desk-actions flex flex-wrap justify-end gap-2"><button className="desk-button-ghost" type="button" disabled={toBuy.isPending} onClick={() => setToBuyTarget(null)}>Cancel</button><button className="desk-button-primary" type="button" disabled={toBuy.isPending} onClick={() => toBuy.mutate()}>Add</button></div>}>
          <div className="grid gap-3 text-sm">
            <p className="font-semibold text-ink">{toBuyTarget?.name}</p>
            <Field label="Quantity"><input className="desk-input" type="number" min="1" value={toBuyQty} onChange={(e) => setToBuyQty(e.target.value)} /></Field>
            {toBuy.error ? <p className="text-sm text-danger">{toBuy.error.message}</p> : null}
          </div>
        </Modal>
      ) : null}
      <Modal open={Boolean(fixTarget)} onClose={() => setFixTarget(null)} title="Move to Fix Shelf" footer={<div className="desk-actions flex flex-wrap justify-end gap-2"><button className="desk-button-ghost" type="button" disabled={moveToFix.isPending} onClick={() => setFixTarget(null)}>Cancel</button><button className="desk-button-warn" type="button" disabled={moveToFix.isPending || !fixTarget || Number(fixQty) < 1 || Number(fixQty) > (fixTarget?.available_quantity ?? 0)} onClick={() => moveToFix.mutate()}>Move to Fix Shelf</button></div>}>
        <div className="grid gap-3 text-sm">
          <p className="font-semibold text-ink">{fixTarget?.name}</p>
          <p className="text-muted">Move available units out of circulation for repair.</p>
          <Field label={`Quantity (${fixTarget?.available_quantity ?? 0} available)`}><input className="desk-input" type="number" min="1" max={fixTarget?.available_quantity ?? 1} value={fixQty} onChange={(e) => setFixQty(e.target.value)} /></Field>
          {moveToFix.error ? <p className="text-sm text-danger">{moveToFix.error.message}</p> : null}
        </div>
      </Modal>
      <Modal open={Boolean(assetFixTarget)} onClose={() => setAssetFixTarget(null)} title={assetFixTarget ? `Choose Asset to Fix - ${assetFixTarget.name}` : "Choose Asset to Fix"} footer={<div className="desk-actions flex flex-wrap justify-end gap-2"><button className="desk-button-ghost" type="button" onClick={() => setAssetFixTarget(null)}>Close</button></div>}>
        {assetFixTarget ? <IndividualAssets productId={assetFixTarget.id} makerspaceId={makerspace.id} refreshInventory={invalidate} /> : null}
      </Modal>
      <ConfirmDialog open={Boolean(archiveTarget)} title="Archive item" message={archiveTarget ? `Archive ${archiveTarget.name}? It will be hidden from active inventory views.` : ""} confirmLabel="Archive" tone="danger" pending={archive.isPending} onCancel={() => setArchiveTarget(null)} onConfirm={() => { if (archiveTarget) archive.mutate(archiveTarget); }} />
      <ConfirmDialog open={qrConfirm !== null} title={qrConfirm ? "Enable public QR" : "Disable public QR"} message={`${qrConfirm ? "Enable" : "Disable"} public self-checkout QR for ${selectedIds.length} selected items?`} confirmLabel={qrConfirm ? "Enable" : "Disable"} pending={bulkQr.isPending} onCancel={() => setQrConfirm(null)} onConfirm={() => { if (qrConfirm !== null) bulkQr.mutate(qrConfirm); }} />
    </Panel>
  );
}

function ItemModal({ title, open, onClose, form, setForm, categories, includeQuantities = false, pending, error, onSubmit, children }: {
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

function QuantityAdjust({ product, form, setForm, pending, error, onSubmit }: { product: AdminProduct; form: AdjustmentForm; setForm: (updater: (current: AdjustmentForm) => AdjustmentForm) => void; pending: boolean; error?: string; onSubmit: () => void }) {
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

function QrHistory({ title, queryKey, path }: { title: string; queryKey: unknown[]; path: string }) {
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

function IndividualAssets({ productId, makerspaceId, refreshInventory }: { productId: number; makerspaceId: number; refreshInventory: () => void }) {
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
function LendingHistory({ productId }: { productId: number }) {
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

function payloadFromForm(form: ItemForm, includeQuantities: boolean) {
  return {
    name: form.name.trim(), tracking_mode: form.tracking_mode, category: form.category ? Number(form.category) : null, description: form.description,
    storage_location: form.storage_location, is_public: form.is_public, public_self_checkout_enabled: form.public_self_checkout_enabled,
    show_public_count: form.show_public_count, public_availability_mode: form.public_availability_mode,
    ...(includeQuantities ? { total_quantity: Number(form.total_quantity || 0), available_quantity: Number(form.available_quantity || 0) } : {}),
  };
}

function adjustPayload(form: AdjustmentForm) {
  return { delta_available: Number(form.delta_available || 0), delta_damaged: Number(form.delta_damaged || 0), delta_lost: Number(form.delta_lost || 0), reason: form.reason.trim() };
}

function formFromProduct(product: AdminProduct): ItemForm {
  return { name: product.name, tracking_mode: product.tracking_mode, category: product.category ? String(product.category) : "", description: product.description, total_quantity: String(product.total_quantity), available_quantity: String(product.available_quantity), storage_location: product.storage_location ?? "", is_public: product.is_public, public_self_checkout_enabled: product.public_self_checkout_enabled, show_public_count: product.show_public_count, public_availability_mode: product.public_availability_mode };
}

function InventoryAvailability({ product }: { product: AdminProduct }) {
  const isLowStock = product.available_quantity <= Math.ceil(product.total_quantity * 0.2);
  const badge = product.available_quantity <= 0 ? <StatusBadge status="lost" label="Unavailable" /> : isLowStock ? <StatusBadge status="limited" label="Limited" /> : <StatusBadge status="available" label="Available" />;
  return <span className="inline-flex items-center gap-2"><span className="inline-block w-8 font-medium tabular-nums text-ink">{product.available_quantity}</span>{badge}</span>;
}

function defaultToBuyQuantity(product: AdminProduct) {
  const target = Math.ceil(product.total_quantity * 0.2) + 1;
  return String(Math.max(1, target - product.available_quantity));
}

function InventoryMetric({ label, value }: { label: string; value: number }) {
  const tones: Record<string, string> = {
    Available: "border-success bg-success/15",
    Damaged: "border-warn bg-warn/15",
    Lost: "border-secondary bg-secondary/15",
  };
  return <div className={`rounded-md border p-3 ${tones[label] ?? "border-accent bg-accent/15"}`}><p className="eyebrow">{label}</p><p className="mt-1 font-mono text-xl font-bold text-ink">{value}</p></div>;
}

function AttributionLine({ acceptedBy, issuedBy }: { acceptedBy: Actor | null; issuedBy: Actor | null }) {
  const parts = [
    acceptedBy ? `Accepted by ${formatActor(acceptedBy)}` : "",
    issuedBy ? `Issued by ${formatActor(issuedBy)}` : "",
  ].filter(Boolean);
  return parts.length ? <p className="text-xs text-muted">{parts.join(" | ")}</p> : null;
}

function formatActor(actor: Actor) {
  return actor.role ? `${actor.username} (${actor.role})` : actor.username;
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/^\w/, (match) => match.toUpperCase());
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
