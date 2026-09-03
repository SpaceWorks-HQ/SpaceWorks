import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import QrScanner from "../../../components/ui/QrScanner";
import { staffRequest, type StaffAuthUser } from "../../../lib/api";
import { Panel, type Makerspace, type Product, useStaffGet } from "./shared";
import { invalidateInventoryViews, invalidateQrViews } from "../queryInvalidation";
import { rows, type BoxContents, type ListResponse, type Rebound, type Resolved } from "./ScannerPanelTypes";
import { ScannerMoveAssetForm, ScannerRebindForm } from "./ScannerPanelForms";

// The staff scanner page existed as an orphan route with dead action badges. This wires
// the staff-reachable allowed_actions the backend returns: revoke (MANAGE_QR) and box
// contents. checkout/return/direct_handout need a borrower identifier, so we point staff
// to the Direct handout / self-checkout flows instead of faking them here.
export function ScannerPanel({ makerspace, isSuperadmin, makerspaces }: {
  makerspace: Makerspace;
  isSuperadmin: boolean;
  makerspaces: Makerspace[];
}) {
  const queryClient = useQueryClient();
  const [payload, setPayload] = useState("");
  const [scanNote, setScanNote] = useState("");
  const [showScanner, setShowScanner] = useState(false);
  const [resolved, setResolved] = useState<Resolved | null>(null);
  const [contents, setContents] = useState<BoxContents | null>(null);
  const [showRebind, setShowRebind] = useState(false);
  const [showMove, setShowMove] = useState(false);
  const [selectedProductId, setSelectedProductId] = useState("");
  const [destMakerspaceId, setDestMakerspaceId] = useState("");
  const [destProductId, setDestProductId] = useState("");
  const [newName, setNewName] = useState("");
  const [moveTag, setMoveTag] = useState("");
  const [successNote, setSuccessNote] = useState<string | null>(null);
  const resolvedQrMakerspaceId = resolved?.qr.makerspace_id ?? resolved?.qr.makerspace;
  const rebindMakerspaceId = resolvedQrMakerspaceId ?? makerspace.id;
  const rebindMakerspace = makerspaces.find((space) => space.id === rebindMakerspaceId) ?? (
    makerspace.id === rebindMakerspaceId ? makerspace : undefined
  );

  const products = useStaffGet<ListResponse<Product>>(
    ["inventory-all", rebindMakerspaceId],
    `/admin/makerspace/${rebindMakerspaceId}/inventory?page_size=1000`,
    showRebind && Boolean(resolvedQrMakerspaceId),
  );
  const destinationProducts = useStaffGet<ListResponse<Product>>(
    ["inventory-all", destMakerspaceId],
    `/admin/makerspace/${destMakerspaceId}/inventory?page_size=1000`,
    Boolean(destMakerspaceId),
  );
  const currentUser = useStaffGet<StaffAuthUser>(["staff", "me"], "/auth/me");
  const productRows = useMemo(() => rows(products.data), [products.data]);
  const destinationProductRows = useMemo(
    () => rows(destinationProducts.data).filter((product) => product.tracking_mode === "individual"),
    [destinationProducts.data],
  );

  const resolve = useMutation({
    mutationFn: (value: string) =>
      staffRequest<Resolved>("/admin/qr/resolve", { method: "POST", body: JSON.stringify({ payload: value.trim() }) }),
    onSuccess: (data) => {
      setResolved(data);
      setContents(null);
      setScanNote("");
      setShowRebind(false);
      setShowMove(false);
      setSelectedProductId("");
      setDestMakerspaceId("");
      setDestProductId("");
      setNewName("");
      setMoveTag("");
      setSuccessNote(null);
    },
  });
  const revoke = useMutation({
    mutationFn: (qrId: number) => staffRequest(`/admin/qr/${qrId}/revoke`, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => {
      if (resolvedQrMakerspaceId) invalidateQrViews(queryClient, resolvedQrMakerspaceId, resolved?.qr.id);
      if (resolved) resolve.mutate(resolved.qr.payload);
    },
  });
  const loadContents = useMutation({
    mutationFn: (boxId: number) => staffRequest<BoxContents>(`/admin/containers/${boxId}/contents`),
    onSuccess: setContents,
  });
  const rebind = useMutation({
    mutationFn: () =>
      staffRequest<Rebound>(`/admin/qr/${resolved?.qr.id}/rebind-target`, {
        method: "POST",
        body: JSON.stringify({
          target_type: "product",
          target_id: Number(selectedProductId),
          new_name: newName.trim() || undefined,
        }),
      }),
    onSuccess: (data) => {
      if (resolvedQrMakerspaceId) invalidateInventoryViews(queryClient, resolvedQrMakerspaceId);
      invalidateQrViews(queryClient, data.qr.makerspace_id ?? data.qr.makerspace, data.qr.id);
      setShowRebind(false);
      setNewName("");
      setSuccessNote("Rebound.");
      resolve.mutate(data.qr.payload, {
        onError: () => {
          setResolved(null);
          setContents(null);
          setSuccessNote("Rebound. Re-scan in the destination makerspace to view.");
        },
      });
    },
  });
  const moveAsset = useMutation({
    mutationFn: () => {
      if (!resolved) throw new Error("No QR resolved.");
      return staffRequest<Rebound>(`/admin/qr/${resolved.qr.id}/rebind-target`, {
        method: "POST",
        body: JSON.stringify({
          target_type: "asset",
          target_id: resolved.target.id,
          destination_makerspace_id: Number(destMakerspaceId),
          destination_product_id: destProductId ? Number(destProductId) : undefined,
          new_name: moveTag.trim() || undefined,
        }),
      });
    },
    onSuccess: (data) => {
      if (resolvedQrMakerspaceId) invalidateInventoryViews(queryClient, resolvedQrMakerspaceId);
      if (destMakerspaceId) invalidateInventoryViews(queryClient, Number(destMakerspaceId));
      invalidateQrViews(queryClient, data.qr.makerspace_id ?? data.qr.makerspace, data.qr.id);
      setShowMove(false);
      setDestMakerspaceId("");
      setDestProductId("");
      setMoveTag("");
      setSuccessNote("Moved.");
      resolve.mutate(data.qr.payload, {
        onError: () => {
          setResolved(null);
          setContents(null);
          setSuccessNote("Moved. Re-scan in the destination makerspace to view.");
        },
      });
    },
  });

  useEffect(() => {
    if (!productRows.length) {
      setSelectedProductId("");
      return;
    }
    if (!productRows.some((product) => String(product.id) === selectedProductId)) {
      setSelectedProductId(String(productRows[0].id));
    }
  }, [productRows, selectedProductId]);

  const doResolve = (value: string) => {
    setScanNote("");
    if (value.trim()) resolve.mutate(value);
  };
  // Camera scans resolve the opaque token WITHOUT echoing it into the visible
  // input (the payload is a physical-possession token, not something to display).
  const resolveFromScan = (value: string) => {
    setShowScanner(false);
    if (!value.trim()) return;
    setScanNote("Scanned - resolving...");
    resolve.mutate(value);
  };
  const target = resolved?.target;
  const actions = resolved?.allowed_actions ?? [];
  const resolveError = resolve.error instanceof Error ? resolve.error.message : undefined;
  const revokeError = revoke.error instanceof Error ? revoke.error.message : undefined;
  const rebindError = rebind.error instanceof Error ? rebind.error.message : undefined;
  const moveError = moveAsset.error instanceof Error ? moveAsset.error.message : undefined;
  const productError = products.error instanceof Error ? products.error.message : undefined;
  const destinationProductError = destinationProducts.error instanceof Error ? destinationProducts.error.message : undefined;
  const rebindActions = currentUser.data?.makerspaces.find(
    (item) => item.id === resolvedQrMakerspaceId,
  )?.actions ?? [];
  const hasRebindPermissions = isSuperadmin || (rebindActions.includes("manage_qr") && rebindActions.includes("edit_inventory"));
  // Rebind UI only targets PRODUCT QRs (the cross-makerspace quantity-product
  // transfer scenario). The form always submits target_type "product", so offering
  // it for an asset QR would silently convert that QR's type - disallow it here.
  const canRebind = Boolean(resolved && target && target.type === "product" && hasRebindPermissions);
  const canMoveAsset = Boolean(resolved && target && target.type === "asset" && isSuperadmin);
  const destinationMakerspaces = makerspaces.filter((space) => space.id !== resolvedQrMakerspaceId);

  return (
    <Panel title="Scanner">
      <p className="mb-3 text-sm text-muted">Scan or paste a QR payload to resolve a box, product, or asset and act on it.</p>
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <input
          aria-label="QR payload"
          className="desk-input w-full font-mono sm:flex-1"
          placeholder="Paste QR payload (or scan)"
          value={payload}
          onChange={(event) => setPayload(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter") doResolve(payload); }}
        />
        <button className="desk-button-primary w-full sm:w-auto" type="button" disabled={!payload.trim() || resolve.isPending} onClick={() => doResolve(payload)}>
          {resolve.isPending ? "Resolving..." : "Resolve"}
        </button>
        <button className="desk-button-ghost w-full sm:w-auto" type="button" onClick={() => { setScanNote(""); setShowScanner(true); }}>Scan camera</button>
      </div>
      {scanNote && resolve.isPending ? <p className="mt-2 text-sm text-accent-ink">{scanNote}</p> : null}
      {resolveError ? <p className="mt-2 text-sm text-danger">{resolveError}</p> : null}
      {successNote ? <p className="mt-2 text-sm text-accent-ink">{successNote}</p> : null}

      {resolved && target ? (
        <div className="mt-4 rounded-md border border-line bg-surface p-3">
          <h3 className="title-section">
            {target.type === "box" ? `Box: ${target.label} (${target.code})`
              : target.type === "product" ? `Product: ${target.name}`
              : `Asset: ${target.asset_tag} - ${target.product} (${target.status})`}
          </h3>
          <p className="mt-1 font-mono text-xs text-muted">QR #{resolved.qr.id} - {resolved.qr.status}</p>
          <div className="desk-actions mt-3 flex flex-wrap gap-2 text-sm">
            {actions.includes("contents") && target.type === "box" ? (
              <button className="desk-button-ghost" type="button" disabled={loadContents.isPending} onClick={() => loadContents.mutate(target.id)}>View contents</button>
            ) : null}
            {actions.includes("revoke") ? (
              <button type="button" className="desk-button-danger" disabled={revoke.isPending} onClick={() => revoke.mutate(resolved.qr.id)}>
                {revoke.isPending ? "Revoking..." : "Revoke QR"}
              </button>
            ) : null}
            {canRebind ? (
              <button className="desk-button-ghost" type="button" onClick={() => setShowRebind((open) => !open)}>
                Rename & rebind
              </button>
            ) : null}
            {canMoveAsset ? (
              <button className="desk-button-ghost" type="button" onClick={() => setShowMove((open) => !open)}>
                Move to makerspace
              </button>
            ) : null}
          </div>
          {showRebind ? (
            <ScannerRebindForm
              makerspaceLabel={rebindMakerspace?.name ?? `Makerspace #${rebindMakerspaceId}`}
              productRows={productRows}
              productsLoading={products.isLoading}
              selectedProductId={selectedProductId}
              onSelectProduct={setSelectedProductId}
              newName={newName}
              onNewNameChange={setNewName}
              pending={rebind.isPending}
              onSubmit={() => rebind.mutate()}
              onCancel={() => setShowRebind(false)}
              productError={productError}
              rebindError={rebindError}
            />
          ) : null}
          {canMoveAsset && showMove ? (
            <ScannerMoveAssetForm
              destinationMakerspaces={destinationMakerspaces}
              destMakerspaceId={destMakerspaceId}
              onDestMakerspaceChange={(value) => {
                setDestMakerspaceId(value);
                setDestProductId("");
              }}
              destProductId={destProductId}
              onDestProductChange={setDestProductId}
              destinationProductRows={destinationProductRows}
              destinationProductsLoading={destinationProducts.isLoading}
              moveTag={moveTag}
              onMoveTagChange={setMoveTag}
              pending={moveAsset.isPending}
              onSubmit={() => moveAsset.mutate()}
              onCancel={() => setShowMove(false)}
              destinationProductError={destinationProductError}
              moveError={moveError}
            />
          ) : null}
          {actions.some((action) => ["checkout", "return", "direct_handout"].includes(action)) ? (
            <p className="mt-2 text-xs text-muted">
              This item supports {actions.filter((a) => ["checkout", "return", "direct_handout"].includes(a)).join(" / ")} -
              use the Direct handout tab (or the public self-checkout page) which collect the borrower identity.
            </p>
          ) : null}
          {revokeError ? <p className="mt-2 text-sm text-danger">{revokeError}</p> : null}
          {contents ? (
            <div className="mt-3 rounded-md border border-line bg-bg p-2 text-xs text-muted">
              <h4 className="title-section">Contents</h4>
              {contents.products.map((product) => <p key={`p-${product.id}`}>{product.name} - {product.available_quantity} available</p>)}
              {contents.assets.map((asset) => <p key={`a-${asset.id}`}>{asset.asset_tag} ({asset.status})</p>)}
              {!contents.products.length && !contents.assets.length ? <p>Empty.</p> : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {showScanner ? <QrScanner onScan={resolveFromScan} onClose={() => setShowScanner(false)} /> : null}
    </Panel>
  );
}
