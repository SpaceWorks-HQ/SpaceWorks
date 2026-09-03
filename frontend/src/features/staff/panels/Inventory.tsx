import type { Key } from "react";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog, DataTable, Field, FilterBar, Modal, StatusBadge } from "../../../components/ui";
import type { DataTableColumn } from "../../../components/ui";
import { downloadStaffFile, staffRequest } from "../../../lib/api";
import { useDebouncedValue } from "../../../lib/useDebouncedValue";
import { readStorage, writeStorage } from "../../../lib/safeStorage";
import { ImageUploader } from "../ImageUploader";
import { ChainOfCustodyBlock } from "./LoanTimeline";
import { invalidateInventoryViews } from "../queryInvalidation";
import { categoryResults, Panel, type CategoryListResponse, type Makerspace, useStaffGet } from "./shared";
import {
  adjustPayload,
  defaultToBuyQuantity,
  emptyAdjust,
  emptyForm,
  formFromProduct,
  payloadFromForm,
  type AdjustmentForm,
  type AdminProduct,
  type ItemForm,
} from "./InventoryPanelShared";
import {
  IndividualAssets,
  InventoryAvailability,
  ItemModal,
  LendingHistory,
  QrHistory,
  QuantityAdjust,
} from "./InventoryPanelParts";

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
