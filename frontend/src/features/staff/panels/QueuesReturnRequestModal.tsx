import { useEffect, useState } from "react";

import { Modal } from "../../../components/ui/Modal";
import { staffRequest } from "../../../lib/api";
import { EvidenceUpload } from "./EvidenceUpload";
import { BoxCodeField, ErrorText, FormFooter, ShelfLine, submitForm } from "./QueuesModalShared";
import type { AssetReturnOutcome, FormModalProps, ReturnRequestValues } from "./QueuesModalTypes";

type PendingOutcome = AssetReturnOutcome | "pending";

type AssetOutcomeState = Record<number, Record<number, PendingOutcome>>;

export function ReturnRequestModal({ row, open, pending, error, onClose, onSubmit, makerspaceId }: FormModalProps<ReturnRequestValues> & { makerspaceId: number }) {
  const [evidenceId, setEvidenceId] = useState<number | null>(null);
  const [boxCode, setBoxCode] = useState(row?.assigned_box?.code ?? "");
  const [remark, setRemark] = useState("");
  const [resolutions, setResolutions] = useState<ReturnRequestValues["resolutions"]>([]);
  const [assetOutcomes, setAssetOutcomes] = useState<AssetOutcomeState>({});
  const [validationError, setValidationError] = useState("");
  const [issueUrl, setIssueUrl] = useState("");

  useEffect(() => {
    if (!open || !row) {
      setIssueUrl("");
      return;
    }
    setEvidenceId(null);
    setBoxCode(row.assigned_box?.code ?? "");
    setRemark("");
    setValidationError("");
    setIssueUrl("");
    setResolutions(row.items.map((item) => item.requires_asset_qr ? { item_id: item.id, returned: 0, damaged: 0, missing: 0, assets: [] } : {
      item_id: item.id,
      returned: remainingCount(item),
      damaged: 0,
      missing: 0,
    }));
    setAssetOutcomes(Object.fromEntries(row.items.filter((item) => item.requires_asset_qr).map((item) => [item.id, Object.fromEntries((item.issued_assets ?? []).map((asset) => [asset.asset_id, "returned"]))])));
  }, [open, row]);

  useEffect(() => {
    if (!open || !row?.issue_evidence_id) {
      setIssueUrl("");
      return;
    }
    let cancelled = false;
    staffRequest<{ url: string }>(`/admin/evidence/${row.issue_evidence_id}`)
      .then((result) => {
        if (!cancelled) setIssueUrl(result.url);
      })
      .catch(() => {
        if (!cancelled) setIssueUrl("");
      });
    return () => {
      cancelled = true;
    };
  }, [open, row?.issue_evidence_id]);

  const updateResolution = (itemId: number, key: "returned" | "damaged" | "missing", value: string) => {
    setResolutions((current) => current.map((resolution) => (resolution.item_id === itemId ? { ...resolution, [key]: Number(value) || 0 } : resolution)));
  };

  const updateAssetOutcome = (itemId: number, assetId: number, outcome: PendingOutcome) => {
    setAssetOutcomes((current) => ({ ...current, [itemId]: { ...(current[itemId] ?? {}), [assetId]: outcome } }));
  };

  return (
    <Modal open={open} onClose={onClose} title={row ? `Return request #${row.id}` : "Return request"} footer={<FormFooter formId="return-request-form" pending={pending} submitLabel="Submit return" onCancel={onClose} />}>
      <form id="return-request-form" className="grid gap-3" onSubmit={(event) => submitForm(event, submitReturn)}>
        <div className="grid gap-3 sm:grid-cols-2">
          {issueUrl ? <div className="grid min-w-0 gap-1 text-sm"><span className="font-medium text-ink">Issue photo</span><img src={issueUrl} alt="Issue photo for comparison" className="max-h-56 w-full rounded-md border border-line object-contain" /></div> : null}
          <div className="grid min-w-0 gap-1 text-sm"><span className="font-medium text-ink">Return photo</span><EvidenceUpload makerspaceId={makerspaceId} evidenceType="return" disabled={pending} onUploaded={setEvidenceId} /></div>
        </div>
        {row?.assigned_box_label ? <p className="text-xs text-muted">Box: <span className="font-medium text-ink">{row.assigned_box_label}</span></p> : null}
        <BoxCodeField value={boxCode} onChange={setBoxCode} makerspaceId={makerspaceId} pending={pending} />
        <label className="grid gap-1 text-sm"><span className="font-medium text-ink">Remark</span><textarea className="desk-input min-h-20 w-full resize-y" value={remark} disabled={pending} onChange={(event) => setRemark(event.target.value)} /></label>
        <ReturnItems row={row} resolutions={resolutions} assetOutcomes={assetOutcomes} pending={pending} onQuantityChange={updateResolution} onAssetOutcomeChange={updateAssetOutcome} />
        <ErrorText message={validationError || error} />
      </form>
    </Modal>
  );

  function submitReturn() {
    if (evidenceId === null) return setValidationError("Upload a return photo before submitting.");
    if (!remark.trim()) return setValidationError("Return remark is required.");
    const finalResolutions = buildFinalResolutions();
    if (finalResolutions.length === 0) return setValidationError("Resolve at least one item.");
    if (finalResolutions.some((resolution) => resolution.returned < 0 || resolution.damaged < 0 || resolution.missing < 0)) return setValidationError("Resolution quantities cannot be negative.");
    const overReturn = overReturnError(row, finalResolutions);
    if (overReturn) return setValidationError(overReturn);
    onSubmit({ evidenceId, boxCode: boxCode.trim(), remark: remark.trim(), resolutions: finalResolutions });
  }

  function buildFinalResolutions(): ReturnRequestValues["resolutions"] {
    return (row?.items ?? []).map((item) => {
      if (!item.requires_asset_qr) return resolutions.find((entry) => entry.item_id === item.id) ?? { item_id: item.id, returned: 0, damaged: 0, missing: 0 };
      const assets = Object.entries(assetOutcomes[item.id] ?? {}).filter(([, outcome]) => outcome !== "pending").map(([assetId, outcome]) => ({ asset_id: Number(assetId), outcome: outcome as AssetReturnOutcome }));
      const counts = countAssetOutcomes(assets);
      return { item_id: item.id, ...counts, assets };
    }).filter((resolution) => resolution.returned + resolution.damaged + resolution.missing > 0);
  }
}

function ReturnItems({ row, resolutions, assetOutcomes, pending, onQuantityChange, onAssetOutcomeChange }: { row: FormModalProps<ReturnRequestValues>["row"]; resolutions: ReturnRequestValues["resolutions"]; assetOutcomes: AssetOutcomeState; pending: boolean; onQuantityChange: (itemId: number, key: "returned" | "damaged" | "missing", value: string) => void; onAssetOutcomeChange: (itemId: number, assetId: number, outcome: PendingOutcome) => void }) {
  return (
    <div className="grid gap-2">
      <p className="text-sm font-medium text-ink">Return outcomes</p>
      {row?.items.map((item) => item.requires_asset_qr ? <SerializedReturnItem key={item.id} item={item} outcomes={assetOutcomes[item.id] ?? {}} pending={pending} onChange={onAssetOutcomeChange} /> : <QuantityReturnItem key={item.id} item={item} resolution={resolutions.find((entry) => entry.item_id === item.id)} pending={pending} onChange={onQuantityChange} />)}
    </div>
  );
}

function SerializedReturnItem({ item, outcomes, pending, onChange }: { item: NonNullable<FormModalProps<ReturnRequestValues>["row"]>["items"][number]; outcomes: Record<number, PendingOutcome>; pending: boolean; onChange: (itemId: number, assetId: number, outcome: PendingOutcome) => void }) {
  return (
    <div className="rounded-md border border-line p-2">
      <p className="text-sm font-medium text-ink">{item.product_name}</p>
      <ShelfLine location={item.storage_location} />
      <div className="mt-2 grid gap-2">
        {(item.issued_assets ?? []).map((asset) => <label key={asset.asset_id} className="eyebrow grid gap-1 sm:grid-cols-[1fr_auto] sm:items-center"><span className="font-medium text-ink">{asset.asset_tag}{asset.serial_number ? ` - ${asset.serial_number}` : ""}</span><select className="desk-input" value={outcomes[asset.asset_id] ?? "returned"} disabled={pending} onChange={(event) => onChange(item.id, asset.asset_id, event.target.value as PendingOutcome)}><option value="returned">Returned</option><option value="damaged">Damaged</option><option value="missing">Missing</option><option value="pending">Not returned now</option></select></label>)}
      </div>
    </div>
  );
}

function QuantityReturnItem({ item, resolution, pending, onChange }: { item: NonNullable<FormModalProps<ReturnRequestValues>["row"]>["items"][number]; resolution?: ReturnRequestValues["resolutions"][number]; pending: boolean; onChange: (itemId: number, key: "returned" | "damaged" | "missing", value: string) => void }) {
  return (
    <div className="rounded-md border border-line p-2">
      <p className="text-sm font-medium text-ink">{item.product_name}</p>
      <ShelfLine location={item.storage_location} />
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        {(["returned", "damaged", "missing"] as const).map((key) => <label key={key} className="eyebrow grid gap-1"><span className="capitalize">{key}</span><input className="desk-input min-w-0" type="number" min="0" max={remainingCount(item)} value={resolution?.[key] ?? 0} disabled={pending} onChange={(event) => onChange(item.id, key, event.target.value)} /></label>)}
      </div>
    </div>
  );
}

function overReturnError(row: FormModalProps<ReturnRequestValues>["row"], resolutions: ReturnRequestValues["resolutions"]) {
  for (const item of row?.items ?? []) {
    const resolution = resolutions.find((entry) => entry.item_id === item.id);
    if (!resolution) continue;
    const resolved = resolution.returned + resolution.damaged + resolution.missing;
    const remaining = remainingCount(item);
    if (resolved > remaining) {
      return `${item.product_name}: return outcomes (${resolved}) exceed remaining issued quantity (${remaining}).`;
    }
  }
  return "";
}
function countAssetOutcomes(assets: Array<{ outcome: AssetReturnOutcome }>) {
  return {
    returned: assets.filter((asset) => asset.outcome === "returned").length,
    damaged: assets.filter((asset) => asset.outcome === "damaged").length,
    missing: assets.filter((asset) => asset.outcome === "missing").length,
  };
}

function remainingCount(item: NonNullable<FormModalProps<ReturnRequestValues>["row"]>["items"][number]) {
  return item.issued_quantity - item.returned_quantity - item.damaged_quantity - item.missing_quantity;
}

