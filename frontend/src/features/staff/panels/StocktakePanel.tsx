import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../../lib/api";
import { Pagination } from "../../../components/ui/Pagination";
import QrScanner from "../../../components/ui/QrScanner";
import { usePaginatedQuery } from "../../../lib/usePaginatedQuery";
import { Panel, type Makerspace, useStaffGet } from "./shared";
import { invalidateInventoryViews } from "../queryInvalidation";

type StocktakeRow = { id: number; status: string; notes: string; container: number | null };
type StocktakeLine = {
  id: number;
  product: number | null;
  asset: number | null;
  expected_quantity: number;
  counted_quantity: number;
  variance_quantity: number;
  condition: string;
  container: number | null;
  notes: string;
};
type StocktakeDetail = StocktakeRow & { lines: StocktakeLine[] };
type ProductOption = { id: number; name: string; tracking_mode: string };
type ContainerOption = { id: number; label: string; location?: string };
type AssetOption = { id: number; asset_tag: string; serial_number: string; status: string };
type StocktakeScanResult = {
  type: "box" | "asset" | "product";
  container_id?: number;
  asset_id?: number;
  product_id?: number;
  label?: string;
  asset_tag?: string;
  name?: string;
};

const CONDITIONS = ["available", "damaged", "lost", "unknown"];

export function StocktakePanel({ makerspace, isSuperadmin = false }: { makerspace: Makerspace; isSuperadmin?: boolean }) {
  const queryClient = useQueryClient();
  const [openId, setOpenId] = useState<number | null>(null);
  const [createNotes, setCreateNotes] = useState("Cycle count");
  const [createContainerId, setCreateContainerId] = useState("");
  const stocktakes = usePaginatedQuery<StocktakeRow>({
    key: ["stocktakes", makerspace.id],
    path: `/admin/makerspace/${makerspace.id}/stocktakes`,
    resetKey: String(makerspace.id),
  });
  const containers = useStaffGet<{ results: ContainerOption[] }>(["stocktake-containers", makerspace.id], `/admin/makerspace/${makerspace.id}/containers?page_size=1000`);
  const create = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/makerspace/${makerspace.id}/stocktakes`, {
        method: "POST",
        body: JSON.stringify({
          notes: createNotes,
          container_id: createContainerId ? Number(createContainerId) : null,
        }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["stocktakes", makerspace.id] }),
  });
  const action = useMutation({
    mutationFn: (path: string) => staffRequest(path, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: (_data, path) => {
      queryClient.invalidateQueries({ queryKey: ["stocktakes", makerspace.id] });
      if (path.endsWith("/apply-adjustments")) {
        invalidateInventoryViews(queryClient, makerspace.id);
        queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspace.id] });
      }
    },
  });
  const createError = create.error instanceof Error ? create.error.message : undefined;
  const actionError = action.error instanceof Error ? action.error.message : undefined;

  return (
    <Panel title="Stocktake">
      <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <label className="eyebrow grid gap-1">
          <span>Session notes</span>
          <input className="desk-input" value={createNotes} onChange={(event) => setCreateNotes(event.target.value)} />
        </label>
        <label className="eyebrow grid gap-1">
          <span>Container</span>
          <select className="desk-input" value={createContainerId} onChange={(event) => setCreateContainerId(event.target.value)}>
            <option value="">All containers</option>
            {containers.data?.results.map((container) => <option key={container.id} value={container.id}>{container.label}</option>)}
          </select>
        </label>
        <button className="desk-button-primary" disabled={create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? "Starting..." : "Start stocktake"}
        </button>
      </div>
      {createError ? <p className="mt-2 text-sm text-danger">{createError}</p> : null}
      {actionError ? <p className="mt-2 text-sm text-danger">{actionError}</p> : null}
      <div className="mt-3 grid gap-2">
        {stocktakes.results.map((row) => (
          <div key={row.id} className="rounded-md border border-line bg-surface p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <strong className="font-mono">#{row.id}</strong>
              <span className="rounded-md border border-line bg-bg px-2 py-0.5 text-xs text-muted">{row.status}</span>
              {canCount(row.status) ? (
                <button className="desk-button-ghost" type="button" onClick={() => setOpenId((id) => (id === row.id ? null : row.id))}>{openId === row.id ? "Hide counts" : "Count items"}</button>
              ) : null}
              {row.status === "counting" ? (
                <button className="desk-button-success" type="button" disabled={action.isPending} onClick={() => action.mutate(`/admin/stocktakes/${row.id}/complete`)}>Complete</button>
              ) : null}
              {isSuperadmin && row.status === "completed" ? (
                <button className="desk-button-success" type="button" disabled={action.isPending} onClick={() => action.mutate(`/admin/stocktakes/${row.id}/approve`)}>Approve</button>
              ) : null}
              {isSuperadmin && row.status === "approved" ? (
                <button className="desk-button-success" type="button" disabled={action.isPending} onClick={() => action.mutate(`/admin/stocktakes/${row.id}/apply-adjustments`)}>Apply</button>
              ) : null}
            </div>
            <p className="mt-1 text-muted">{row.notes}{row.container ? ` ? Container #${row.container}` : ""}</p>
            {openId === row.id ? <CountSection makerspace={makerspace} stocktakeId={row.id} /> : null}
          </div>
        ))}
      </div>
      <Pagination page={stocktakes.page} totalPages={stocktakes.totalPages} onChange={stocktakes.setPage} count={stocktakes.count} pageSize={stocktakes.pageSize} />
    </Panel>
  );
}

// The count step is what moves a stocktake forward and produces the variance the Apply
// step adjusts on - without it a stocktake has zero lines and Apply is a no-op. Records
// a counted quantity per product, then shows expected/counted/variance from the detail.
function CountSection({ makerspace, stocktakeId }: { makerspace: Makerspace; stocktakeId: number }) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"product" | "asset">("product");
  const [productId, setProductId] = useState("");
  const [assetId, setAssetId] = useState("");
  const [containerId, setContainerId] = useState("");
  const [counted, setCounted] = useState("0");
  const [condition, setCondition] = useState("available");
  const [notes, setNotes] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanNote, setScanNote] = useState("");
  const detail = useStaffGet<StocktakeDetail>(["stocktake-detail", stocktakeId], `/admin/stocktakes/${stocktakeId}`);
  const products = useStaffGet<{ results: ProductOption[] }>(["inventory-all", makerspace.id], `/admin/makerspace/${makerspace.id}/inventory?page_size=1000`);
  const containers = useStaffGet<{ results: ContainerOption[] }>(["stocktake-containers", makerspace.id], `/admin/makerspace/${makerspace.id}/containers?page_size=1000`);
  const assets = useStaffGet<{ results: AssetOption[] }>(["stocktake-assets", productId], productId ? `/admin/inventory/${productId}/assets?page_size=1000` : "", Boolean(productId));
  const productName = (id: number | null) => products.data?.results.find((product) => product.id === id)?.name ?? (id ? `#${id}` : "-");
  const assetName = (id: number | null) => assets.data?.results.find((asset) => asset.id === id)?.asset_tag ?? (id ? `Asset #${id}` : "-");
  const containerName = (id: number | null) => containers.data?.results.find((container) => container.id === id)?.label ?? (id ? `Container #${id}` : "-");

  const record = useMutation({
    mutationFn: () => {
      const payload = {
        ...(mode === "asset" ? { asset_id: Number(assetId) } : { product_id: Number(productId) }),
        ...(containerId ? { container_id: Number(containerId) } : {}),
        counted_quantity: Number(counted) || 0,
        condition,
        notes,
      };
      return staffRequest(`/admin/stocktakes/${stocktakeId}/count-lines`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    onSuccess: () => {
      setProductId("");
      setAssetId("");
      setContainerId("");
      setCounted("0");
      setNotes("");
      queryClient.invalidateQueries({ queryKey: ["stocktake-detail", stocktakeId] });
      queryClient.invalidateQueries({ queryKey: ["stocktakes", makerspace.id] });
    },
  });
  const handleScan = async (payload: string) => {
    try {
      const result = await staffRequest<StocktakeScanResult>(`/admin/stocktakes/${stocktakeId}/resolve-scan`, {
        method: "POST",
        body: JSON.stringify({ payload }),
      });
      if (result.type === "asset" && result.asset_id && result.product_id) {
        setMode("asset");
        setProductId(String(result.product_id));
        setAssetId(String(result.asset_id));
      } else if (result.type === "product" && result.product_id) {
        setMode("product");
        setProductId(String(result.product_id));
        setAssetId("");
      } else if (result.type === "box" && result.container_id) {
        setContainerId(String(result.container_id));
      }
      setScanNote(`Scanned ${result.asset_tag || result.name || result.label || payload}`);
      setScanning(false);
    } catch (error) {
      setScanNote(error instanceof Error ? error.message : "Unable to resolve scanned QR");
      setScanning(false);
    }
  };
  const recordError = record.error instanceof Error ? record.error.message : undefined;
  const lines = detail.data?.lines ?? [];
  const canSave = mode === "asset" ? Boolean(assetId) : Boolean(productId);

  return (
    <div className="mt-3 rounded-md border border-line bg-bg p-3">
      <div className="grid gap-2 md:grid-cols-[120px_1fr_1fr_120px_140px] md:items-end">
        <label className="eyebrow grid gap-1">
          <span>Count type</span>
          <select className="desk-input" value={mode} onChange={(event) => { setMode(event.target.value as "product" | "asset"); setAssetId(""); }}>
            <option value="product">Product</option>
            <option value="asset">Asset</option>
          </select>
        </label>
        <label className="eyebrow grid gap-1">
          <span>{mode === "asset" ? "Product for asset" : "Product"}</span>
          <select className="desk-input" value={productId} disabled={products.isLoading} onChange={(event) => { setProductId(event.target.value); setAssetId(""); }}>
            <option value="">Select product</option>
            {products.data?.results.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
          </select>
        </label>
        {mode === "asset" ? (
          <label className="eyebrow grid gap-1">
            <span>Asset</span>
            <select className="desk-input" value={assetId} disabled={!productId || assets.isLoading} onChange={(event) => setAssetId(event.target.value)}>
              <option value="">Select asset</option>
              {assets.data?.results.map((asset) => <option key={asset.id} value={asset.id}>{asset.asset_tag} ({asset.status})</option>)}
            </select>
          </label>
        ) : (
          <label className="eyebrow grid gap-1">
            <span>Line container</span>
            <select className="desk-input" value={containerId} onChange={(event) => setContainerId(event.target.value)}>
              <option value="">No container</option>
              {containers.data?.results.map((container) => <option key={container.id} value={container.id}>{container.label}</option>)}
            </select>
          </label>
        )}
        <label className="eyebrow grid gap-1">
          <span>Counted</span>
          <input className="desk-input" type="number" min="0" value={counted} onChange={(event) => setCounted(event.target.value)} />
        </label>
        <label className="eyebrow grid gap-1">
          <span>Condition</span>
          <select className="desk-input" value={condition} onChange={(event) => setCondition(event.target.value)}>
            {CONDITIONS.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
      </div>
      {mode === "asset" ? (
        <label className="eyebrow mt-2 grid gap-1">
          <span>Line container</span>
          <select className="desk-input" value={containerId} onChange={(event) => setContainerId(event.target.value)}>
            <option value="">No container</option>
            {containers.data?.results.map((container) => <option key={container.id} value={container.id}>{container.label}</option>)}
          </select>
        </label>
      ) : null}
      <label className="eyebrow mt-2 grid gap-1">
        <span>Line notes</span>
        <input className="desk-input" value={notes} onChange={(event) => setNotes(event.target.value)} />
      </label>
      <div className="desk-actions mt-2 flex justify-between gap-2">
        <button className="desk-button-ghost" type="button" onClick={() => setScanning(true)}>Scan QR</button>
        <button className="desk-button-primary" disabled={!canSave || record.isPending} onClick={() => record.mutate()}>{record.isPending ? "Saving..." : "Record count"}</button>
      </div>
      {scanNote ? <p className={`mt-2 text-sm ${scanNote.startsWith("Scanned ") ? "text-muted" : "text-danger"}`}>{scanNote}</p> : null}
      {recordError ? <p className="mt-2 text-sm text-danger">{recordError}</p> : null}
      {scanning ? <QrScanner onClose={() => setScanning(false)} onScan={handleScan} /> : null}
      <div className="mt-3 grid min-w-0 gap-1">
        {lines.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-[720px] text-left text-xs">
              <thead className="text-muted">
                <tr><th className="py-1">Item</th><th>Container</th><th>Expected</th><th>Counted</th><th>Variance</th><th>Condition</th><th>Notes</th></tr>
              </thead>
              <tbody>
                {lines.map((line) => (
                  <tr key={line.id} className="border-t border-line">
                    <td className="py-1"><span className="block max-w-48 break-words">{line.asset ? assetName(line.asset) : productName(line.product)}</span></td>
                    <td>{containerName(line.container)}</td>
                    <td className="font-mono">{line.expected_quantity}</td>
                    <td className="font-mono">{line.counted_quantity}</td>
                    <td className={line.variance_quantity === 0 ? "font-mono text-muted" : "font-mono text-danger"}>{line.variance_quantity}</td>
                    <td>{line.condition}</td>
                    <td><span className="block max-w-56 break-words">{line.notes || "-"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="text-xs text-muted">No counts recorded yet.</p>}
      </div>
    </div>
  );
}

function canCount(status: string) {
  return status === "draft" || status === "counting";
}
