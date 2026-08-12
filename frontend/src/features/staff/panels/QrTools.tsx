import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Modal } from "../../../components/ui/Modal";
import { downloadStaffFile, staffRequest } from "../../../lib/api";
import { Panel, type Makerspace, type Product, useStaffGet } from "./shared";
import { QrImage } from "./QrImage";
import { invalidateInventoryViews, invalidateQrViews } from "../queryInvalidation";

type ListResponse<T> = { results: T[] };
type QrCode = { id: number; payload: string; target_type: string; target_id: number };
type AssetRow = { id: number; asset_tag: string; serial_number: string; status: string; box_label: string | null; qr_code_id: number | null; qr_payload: string | null };
type Batch = { id: number; title: string; status: string; created_at: string };
type BatchItem = { id: number; qr_code: QrCode; label_text: string; target_type: string; target_id: number };
type BatchDetail = Batch & { items: BatchItem[] };

export function QrTools({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const [batchId, setBatchId] = useState("");
  const [batchTitle, setBatchTitle] = useState("QR labels");
  const [productId, setProductId] = useState("");
  const [assetId, setAssetId] = useState("");
  const [assetCount, setAssetCount] = useState("50");
  const [assetPrefix, setAssetPrefix] = useState("");
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const batches = useStaffGet<ListResponse<Batch>>(["qr-batches", makerspace.id], `/admin/makerspace/${makerspace.id}/qr-print-batches`);
  const products = useStaffGet<ListResponse<Product>>(["inventory", makerspace.id], `/admin/makerspace/${makerspace.id}/inventory?page_size=1000`);
  const activeBatchId = Number(batchId) || 0;
  const selectedProductId = Number(productId) || 0;
  const batch = useStaffGet<BatchDetail>(["qr-batch", activeBatchId], `/admin/qr-print-batches/${activeBatchId}`, Boolean(activeBatchId));

  useEffect(() => {
    if (!batchId && batches.data?.results?.length) {
      setBatchId(String(batches.data.results[0].id));
    }
  }, [batchId, batches.data?.results]);

  const productOptions = products.data?.results?.filter((product) => !product.is_archived) ?? [];
  const selectedProduct = useMemo(
    () => productOptions.find((product) => product.id === selectedProductId),
    [selectedProductId, productOptions],
  );
  const selectedIsIndividual = selectedProduct?.tracking_mode === "individual";
  const assets = useStaffGet<ListResponse<AssetRow>>(
    ["inventory-assets", selectedProductId],
    `/admin/inventory/${selectedProductId}/assets`,
    Boolean(selectedIsIndividual && selectedProductId),
  );

  const refreshBatch = () => {
    queryClient.invalidateQueries({ queryKey: ["qr-batches", makerspace.id] });
    if (activeBatchId) queryClient.invalidateQueries({ queryKey: ["qr-batch", activeBatchId] });
  };
  const createBatch = useMutation({
    mutationFn: () =>
      staffRequest<Batch>(`/admin/makerspace/${makerspace.id}/qr-print-batches`, {
        method: "POST",
        body: JSON.stringify({ title: batchTitle.trim() }),
      }),
    onSuccess: (created) => {
      setBatchId(String(created.id));
      setBatchModalOpen(false);
      refreshBatch();
    },
  });
  const addItem = async (qrCodeId: number, labelText: string) => {
    await staffRequest(`/admin/qr-print-batches/${activeBatchId}/items`, {
      method: "POST",
      body: JSON.stringify({ qr_code_id: qrCodeId, label_text: labelText }),
    });
  };
  const addProduct = useMutation({
    mutationFn: async () => {
      if (!selectedProduct) throw new Error("Choose an inventory item.");
      if (selectedProduct.tracking_mode === "individual") throw new Error("Generate unit QRs for individual inventory.");
      const qr = await staffRequest<QrCode>("/admin/qr/tools", {
        method: "POST",
        body: JSON.stringify({ makerspace_id: makerspace.id, product_id: selectedProduct.id }),
      });
      await addItem(qr.id, selectedProduct.name);
    },
    onSuccess: refreshBatch,
  });
  const reprintAsset = useMutation({
    mutationFn: async () => {
      const asset = assets.data?.results?.find((item) => item.id === Number(assetId));
      if (!asset) throw new Error("Choose an existing unit.");
      const qr = await staffRequest<QrCode>(`/admin/assets/${asset.id}/qr`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await addItem(qr.id, asset.asset_tag);
    },
    onSuccess: () => {
      invalidateInventoryViews(queryClient, makerspace.id);
      invalidateQrViews(queryClient, makerspace.id);
      queryClient.invalidateQueries({ queryKey: ["inventory-assets", selectedProductId] });
      refreshBatch();
    },
  });
  const generateAssets = useMutation({
    mutationFn: () => {
      if (!selectedProduct) return Promise.reject(new Error("Choose an inventory item."));
      return staffRequest(`/admin/products/${selectedProduct.id}/assets/generate`, {
        method: "POST",
        body: JSON.stringify({
          count: Number(assetCount),
          name_prefix: assetPrefix.trim() || selectedProduct.name,
          print_batch_id: activeBatchId,
        }),
      });
    },
    onSuccess: () => {
      invalidateInventoryViews(queryClient, makerspace.id);
      invalidateQrViews(queryClient, makerspace.id);
      queryClient.invalidateQueries({ queryKey: ["inventory-assets", selectedProductId] });
      refreshBatch();
    },
  });
  const downloadZip = useMutation({
    mutationFn: () =>
      downloadStaffFile(
        `/admin/qr-print-batches/${activeBatchId}/download`,
        `qr-batch-${activeBatchId}.zip`,
      ),
  });
  const hasBatch = Boolean(activeBatchId);
  // Both unit-QR endpoints (`assets/generate` and the per-asset reprint) are guarded by
  // `asset_units` on the backend, so offering the controls without it produces a form
  // whose only outcome is a 404. An empty list means "not loaded", never "none enabled".
  const modules = makerspace.enabled_modules ?? [];
  const assetUnitsEnabled = modules.length === 0 || modules.includes("asset_units");
  const batchItems = batch.data?.items ?? [];
  const count = Number(assetCount);
  const assetOptions = assets.data?.results ?? [];
  const canGenerateAssets = hasBatch && Boolean(selectedProduct) && selectedIsIndividual && Number.isInteger(count) && count > 0 && count <= 200;
  const canReprintAsset = hasBatch && selectedIsIndividual && Boolean(assetId);
  const canAddItemQr = hasBatch && Boolean(selectedProduct) && !selectedIsIndividual;
  const selectProduct = (nextId: string) => {
    setProductId(nextId);
    setAssetId("");
    const product = productOptions.find((item) => item.id === Number(nextId));
    setAssetPrefix(product?.name ?? "");
  };

  return (
    <Panel title="QR tools">
      <div className="grid gap-4">
        <div className="rounded-md border border-line bg-surface p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="eyebrow">Makerspace</p>
              <p className="font-semibold text-ink">{makerspace.name}</p>
            </div>
            <button className="desk-button-primary" type="button" onClick={() => setBatchModalOpen(true)}>
              New batch
            </button>
          </div>
          <select className="desk-input mt-3 w-full" value={batchId} disabled={batches.isLoading} onChange={(event) => setBatchId(event.target.value)}>
            <option value="">Select a print batch</option>
            {batches.data?.results?.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select>
          {batches.isError ? <ErrorText text={batches.error.message} /> : null}
        </div>

        <ActionBox title="Inventory QR">
          <select className="desk-input w-full" value={productId} disabled={!hasBatch || products.isLoading} onChange={(event) => selectProduct(event.target.value)}>
            <option value="">Inventory item</option>
            {productOptions.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name} | {product.tracking_mode} | {product.available_quantity} available
              </option>
            ))}
          </select>
          {selectedProduct ? <p className="mt-2 font-mono text-xs uppercase text-muted">{selectedProduct.tracking_mode}</p> : null}
          {selectedIsIndividual && !assetUnitsEnabled ? (
            <p className="mt-2 text-sm text-muted">
              Unit QR generation needs the Asset units module.
            </p>
          ) : null}
          {selectedIsIndividual && assetUnitsEnabled ? (
            <div className="mt-2 grid gap-3">
              <div className="grid gap-2 sm:grid-cols-[110px_1fr_auto]">
                <input className="desk-input" inputMode="numeric" value={assetCount} onChange={(event) => setAssetCount(event.target.value)} />
                <input className="desk-input" value={assetPrefix} placeholder="Label prefix" onChange={(event) => setAssetPrefix(event.target.value)} />
                <button className="desk-button-primary" type="button" disabled={!canGenerateAssets || generateAssets.isPending} onClick={() => generateAssets.mutate()}>
                  {generateAssets.isPending ? "Generating..." : "Generate missing/new unit QRs"}
                </button>
              </div>
              <div className="grid gap-2 border-t border-line pt-3 sm:grid-cols-[minmax(0,1fr)_auto]">
                <select className="desk-input w-full" value={assetId} disabled={!hasBatch || assets.isLoading} onChange={(event) => setAssetId(event.target.value)}>
                  <option value="">Existing unit to reprint</option>
                  {assetOptions.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {asset.asset_tag} | {asset.status} | {asset.qr_code_id ? `QR #${asset.qr_code_id}` : "no QR linked"}
                    </option>
                  ))}
                </select>
                <button className="desk-button-primary" type="button" disabled={!canReprintAsset || reprintAsset.isPending} onClick={() => reprintAsset.mutate()}>
                  {reprintAsset.isPending ? "Adding..." : "Reprint unit QR"}
                </button>
              </div>
              {assets.isLoading ? <p className="text-sm text-muted">Loading units...</p> : null}
              {assets.isError ? <ErrorText text={assets.error.message} /> : null}
              {!assets.isLoading && selectedProduct && !assetOptions.length ? <p className="text-sm text-muted">No individual units yet.</p> : null}
            </div>
          ) : null}
          {!selectedIsIndividual ? (
            <button className="desk-button-primary mt-2" type="button" disabled={!canAddItemQr || addProduct.isPending} onClick={() => addProduct.mutate()}>
              {addProduct.isPending ? "Adding..." : "Add/reprint item QR"}
            </button>
          ) : null}
          {addProduct.isError ? <ErrorText text={addProduct.error.message} /> : null}
          {reprintAsset.isError ? <ErrorText text={reprintAsset.error.message} /> : null}
          {generateAssets.isError ? <ErrorText text={generateAssets.error.message} /> : null}
        </ActionBox>

        <div className="rounded-md border border-line bg-surface p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="title-section">{batch.data?.title ?? "Working batch"}</h3>
              <p className="text-sm text-muted">{batchItems.length} QR labels accumulated</p>
            </div>
            <button className="desk-button-primary" type="button" disabled={!batchItems.length || downloadZip.isPending} onClick={() => downloadZip.mutate()}>
              {downloadZip.isPending ? "Preparing..." : "Download all (ZIP)"}
            </button>
          </div>
          {batch.isLoading ? <p className="mt-3 text-sm text-muted">Loading batch...</p> : null}
          {batch.isError ? <ErrorText text={batch.error.message} /> : null}
          {!batch.isLoading && !batchItems.length ? <p className="mt-3 text-sm text-muted">No QR labels in this batch.</p> : null}
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {batchItems.map((item) => (
              <article key={item.id} className="rounded-md border border-line bg-bg p-3 text-center">
                <QrImage qrId={item.qr_code.id} label={item.label_text} />
                <p className="mt-2 text-sm font-semibold text-ink">{item.label_text}</p>
                <p className="text-xs text-muted">{item.target_type} #{item.target_id}</p>
              </article>
            ))}
          </div>
          {downloadZip.isError ? <ErrorText text={(downloadZip.error as Error).message} /> : null}
        </div>
      </div>

      <Modal open={batchModalOpen} onClose={() => setBatchModalOpen(false)} title="Create QR print batch" footer={<ModalActions pending={createBatch.isPending} onCancel={() => setBatchModalOpen(false)} onSubmit={() => createBatch.mutate()} submitLabel="Create batch" disabled={!batchTitle.trim()} />}>
        <input className="desk-input w-full" value={batchTitle} onChange={(event) => setBatchTitle(event.target.value)} />
        {createBatch.isError ? <ErrorText text={createBatch.error.message} /> : null}
      </Modal>
    </Panel>
  );
}

function ActionBox({ children, title }: { children: React.ReactNode; title: string }) {
  return <section className="rounded-md border border-line bg-surface p-3"><h3 className="title-section mb-2">{title}</h3>{children}</section>;
}

function ErrorText({ text }: { text: string }) {
  return <p className="mt-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{text}</p>;
}

function ModalActions(props: { pending: boolean; disabled: boolean; submitLabel: string; onCancel: () => void; onSubmit: () => void }) {
  return (
    <div className="flex flex-wrap justify-end gap-2">
      <button className="desk-button-ghost" type="button" disabled={props.pending} onClick={props.onCancel}>Cancel</button>
      <button className="desk-button-primary" type="button" disabled={props.pending || props.disabled} onClick={props.onSubmit}>
        {props.pending ? "Saving..." : props.submitLabel}
      </button>
    </div>
  );
}
