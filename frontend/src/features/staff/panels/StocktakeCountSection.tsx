import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../../lib/api";
import QrScanner from "../../../components/ui/QrScanner";
import { type Makerspace, useStaffGet } from "./shared";

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

// The count step is what moves a stocktake forward and produces the variance the Apply
// step adjusts on - without it a stocktake has zero lines and Apply is a no-op. Records
// a counted quantity per product, then shows expected/counted/variance from the detail.
export function CountSection({ makerspace, stocktakeId }: { makerspace: Makerspace; stocktakeId: number }) {
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
                <tr><th scope="col" className="py-1">Item</th><th scope="col">Container</th><th scope="col">Expected</th><th scope="col">Counted</th><th scope="col">Variance</th><th scope="col">Condition</th><th scope="col">Notes</th></tr>
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

