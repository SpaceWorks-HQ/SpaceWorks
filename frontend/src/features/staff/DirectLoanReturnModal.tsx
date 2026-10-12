import { useEffect, useState } from "react";
import type React from "react";

import { Modal } from "../../components/ui/Modal";
import QrScanner from "../../components/ui/QrScanner";
import { EvidenceUpload } from "./panels/EvidenceUpload";
import type { DirectLoan, DirectLoanReturnItem } from "./DirectLoanList";
import { KitChecklistCapture, useKitChecklist, type KitCount } from "../inventory/KitChecklist";

type AssetOutcome = "returned" | "damaged" | "missing";
type QuantityResolution = { item_id: number; returned: number; damaged: number; missing: number };
type AssetResolution = QuantityResolution & { assets: { asset_id: number; outcome: AssetOutcome }[] };
export type DirectLoanResolution = QuantityResolution | AssetResolution;

type DirectLoanReturnModalProps = {
  loan: DirectLoan | null;
  makerspaceId: number;
  evidenceId: number | null;
  notes: string;
  qrPayload: string;
  pending: boolean;
  error: string;
  onEvidenceUploaded: (evidenceId: number | null) => void;
  onNotesChange: (notes: string) => void;
  onQrPayloadChange: (payload: string) => void;
  onCancel: () => void;
  onSubmit: (resolutions: DirectLoanResolution[], kitChecklist?: KitCount[]) => void;
};

// Quantity buckets per item (non-individual): default everything to "returned".
type QtyState = Record<number, { returned: number; damaged: number; missing: number }>;
// Per-asset outcome for individual-tracked items.
type AssetState = Record<number, Record<number, AssetOutcome>>;

export function DirectLoanReturnModal({
  loan,
  makerspaceId,
  evidenceId,
  notes,
  qrPayload,
  pending,
  error,
  onEvidenceUploaded,
  onNotesChange,
  onQrPayloadChange,
  onCancel,
  onSubmit,
}: DirectLoanReturnModalProps) {
  const [showScanner, setShowScanner] = useState(false);
  const [qtyState, setQtyState] = useState<QtyState>({});
  const [assetState, setAssetState] = useState<AssetState>({});
  const returnItems: DirectLoanReturnItem[] = loan?.return_items ?? [];
  const kits = useKitChecklist(`/admin/makerspace/${makerspaceId}/kit-checklist-preview`,
    { loan_id: loan?.id, phase: "return" }, Boolean(loan?.has_kit_checklist));

  useEffect(() => {
    if (!loan) return;
    const items = loan.return_items ?? [];
    // Default a clean return: quantity items pre-fill returned = remaining; individual
    // items default every still-issued asset to "returned". Staff reclassify as needed.
    setQtyState(
      Object.fromEntries(
        items
          .filter((item) => item.tracking_mode !== "individual")
          .map((item) => [item.item_id, { returned: item.remaining_quantity, damaged: 0, missing: 0 }]),
      ),
    );
    setAssetState(
      Object.fromEntries(
        items
          .filter((item) => item.tracking_mode === "individual")
          .map((item) => [
            item.item_id,
            Object.fromEntries(item.assets.map((asset) => [asset.asset_id, "returned" as AssetOutcome])),
          ]),
      ),
    );
  }, [loan]);

  const scanRequired = Boolean(loan?.return_scan_required);
  const buildResolutions = (): DirectLoanResolution[] =>
    returnItems.map((item) => {
      if (item.tracking_mode === "individual") {
        const outcomes = assetState[item.item_id] ?? {};
        const assets = item.assets.map((asset) => ({
          asset_id: asset.asset_id,
          outcome: outcomes[asset.asset_id] ?? ("returned" as AssetOutcome),
        }));
        return {
          item_id: item.item_id,
          returned: assets.filter((a) => a.outcome === "returned").length,
          damaged: assets.filter((a) => a.outcome === "damaged").length,
          missing: assets.filter((a) => a.outcome === "missing").length,
          assets,
        };
      }
      const buckets = qtyState[item.item_id] ?? { returned: item.remaining_quantity, damaged: 0, missing: 0 };
      return { item_id: item.item_id, ...buckets };
    });

  // Every outstanding unit must be resolved (direct loans have no partial state).
  const fullyResolved = returnItems.every((item) => {
    const r = buildResolutions().find((res) => res.item_id === item.item_id);
    return r ? r.returned + r.damaged + r.missing === item.remaining_quantity : false;
  });
  const canSubmit =
    evidenceId !== null &&
    notes.trim().length > 0 &&
    (!scanRequired || qrPayload.trim().length > 0) &&
    fullyResolved &&
    kits.ready &&
    !pending;

  const updateQty = (itemId: number, key: "returned" | "damaged" | "missing", value: string) => {
    setQtyState((current) => ({
      ...current,
      [itemId]: { ...(current[itemId] ?? { returned: 0, damaged: 0, missing: 0 }), [key]: Number(value) || 0 },
    }));
  };
  const updateAsset = (itemId: number, assetId: number, outcome: AssetOutcome) => {
    setAssetState((current) => ({ ...current, [itemId]: { ...(current[itemId] ?? {}), [assetId]: outcome } }));
  };

  return (
    <Modal
      open={Boolean(loan)}
      onClose={() => {
        if (!pending) onCancel();
      }}
      title={loan ? `Return ${loan.target_label}` : "Return direct handout"}
      footer={
        <div className="desk-actions flex flex-wrap justify-end gap-2">
          <button className="desk-button" type="button" disabled={pending} onClick={onCancel}>
            Cancel
          </button>
          <button className="desk-button" type="submit" form="direct-loan-return-form" disabled={!canSubmit}>
            {pending ? "Returning..." : "Submit return"}
          </button>
        </div>
      }
    >
      <form
        id="direct-loan-return-form"
        className="grid gap-3"
        onSubmit={(event: React.FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          if (canSubmit) onSubmit(buildResolutions(), kits.counts);
        }}
      >
        <div className="grid gap-1 text-sm">
          <KitChecklistCapture checklist={kits} />
          <span className="font-medium text-ink">Return photo</span>
          <EvidenceUpload
            makerspaceId={makerspaceId}
            evidenceType="return"
            disabled={pending}
            onUploaded={onEvidenceUploaded}
          />
        </div>
        {returnItems.length ? (
          <div className="grid gap-2">
            <p className="text-sm font-medium text-ink">Return outcomes</p>
            {returnItems.map((item) =>
              item.tracking_mode === "individual" ? (
                <div key={item.item_id} className="rounded-md border border-line p-2">
                  <p className="text-sm font-medium text-ink">{item.product_name}</p>
                  <div className="mt-2 grid gap-2">
                    {item.assets.map((asset) => (
                      <label
                        key={asset.asset_id}
                        className="grid gap-1 text-xs text-muted sm:grid-cols-[1fr_auto] sm:items-center"
                      >
                        <span className="font-medium text-ink">{asset.asset_tag}</span>
                        <select
                          className="desk-input"
                          value={(assetState[item.item_id] ?? {})[asset.asset_id] ?? "returned"}
                          disabled={pending}
                          onChange={(event) => updateAsset(item.item_id, asset.asset_id, event.target.value as AssetOutcome)}
                        >
                          <option value="returned">Returned</option>
                          <option value="damaged">Damaged</option>
                          <option value="missing">Missing</option>
                        </select>
                      </label>
                    ))}
                  </div>
                </div>
              ) : (
                <div key={item.item_id} className="rounded-md border border-line p-2">
                  <p className="text-sm font-medium text-ink">
                    {item.product_name} <span className="text-xs text-muted">({item.remaining_quantity} out)</span>
                  </p>
                  <div className="mt-2 grid gap-2 sm:grid-cols-3">
                    {(["returned", "damaged", "missing"] as const).map((key) => (
                      <label key={key} className="grid gap-1 text-xs text-muted">
                        <span className="capitalize">{key}</span>
                        <input
                          className="desk-input min-w-0"
                          type="number"
                          min="0"
                          max={item.remaining_quantity}
                          value={(qtyState[item.item_id] ?? { returned: 0, damaged: 0, missing: 0 })[key]}
                          disabled={pending}
                          onChange={(event) => updateQty(item.item_id, key, event.target.value)}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              ),
            )}
            {!fullyResolved ? (
              <p className="text-xs text-warn-ink">Resolve every outstanding unit before submitting.</p>
            ) : null}
          </div>
        ) : null}
        <label className="grid gap-1 text-sm">
          <span className="font-medium text-ink">Return QR scan{scanRequired ? "" : " (optional)"}</span>
          <div className="flex flex-col gap-2 md:flex-row">
            <input
              className="desk-input w-full font-mono text-sm"
              value={qrPayload}
              disabled={pending}
              onChange={(event) => onQrPayloadChange(event.target.value)}
            />
            <button className="desk-button" type="button" disabled={pending} onClick={() => setShowScanner(true)}>
              Scan QR
            </button>
          </div>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium text-ink">Return notes</span>
          <textarea
            className="desk-input min-h-24 w-full resize-y"
            value={notes}
            disabled={pending}
            onChange={(event) => onNotesChange(event.target.value)}
          />
        </label>
        {error ? <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p> : null}
        {showScanner ? (
          <QrScanner
            onScan={(payload) => {
              onQrPayloadChange(payload.trim());
              setShowScanner(false);
            }}
            onClose={() => setShowScanner(false)}
          />
        ) : null}
      </form>
    </Modal>
  );
}
