import { useEffect, useState } from "react";

import { Modal } from "../../../components/ui/Modal";
import QrScanner from "../../../components/ui/QrScanner";
import { staffRequest } from "../../../lib/api";
import { EvidenceUpload } from "./EvidenceUpload";
import { BoxCodeField, ErrorText, FormFooter, ShelfLine, submitForm } from "./QueuesModalShared";
import type { AssignIssueValues, FormModalProps } from "./QueuesModalTypes";

type ScannedAsset = { payload: string; label: string };

export function AssignIssueModal({ row, open, pending, error, onClose, onSubmit, makerspaceId }: FormModalProps<AssignIssueValues> & { makerspaceId: number }) {
  const [boxCode, setBoxCode] = useState(row?.assigned_box?.code ?? "");
  const [evidenceId, setEvidenceId] = useState<number | null>(null);
  const [remark, setRemark] = useState("Issued from staff app.");
  const [rejects, setRejects] = useState<Record<number, { broken: number; disposition: "needs_fix" | "remove" }>>({});
  const [scanned, setScanned] = useState<ScannedAsset[]>([]);
  const [showScanner, setShowScanner] = useState(false);
  const [validationError, setValidationError] = useState("");

  const requiredScans = (row?.items ?? []).filter((item) => item.requires_asset_qr).reduce((sum, item) => sum + item.accepted_quantity, 0);

  useEffect(() => {
    if (open) {
      setBoxCode(row?.assigned_box?.code ?? "");
      setEvidenceId(null);
      setRemark("Issued from staff app.");
      setRejects({});
      setScanned([]);
      setShowScanner(false);
      setValidationError("");
    }
  }, [open, row]);

  const handleScan = async (payload: string) => {
    const clean = payload.trim();
    if (!clean || scanned.some((item) => item.payload === clean)) return;
    let label = "Scanned QR";
    try {
      const result = await staffRequest<{ target: { type: string; product?: string; asset_tag?: string } }>("/admin/qr/resolve", {
        method: "POST",
        body: JSON.stringify({ payload: clean }),
      });
      label = result.target.product || result.target.asset_tag || "Scanned QR";
    } catch {
      label = "Unrecognized QR";
    }
    setScanned((items) => (items.some((item) => item.payload === clean) ? items : [...items, { payload: clean, label }]));
  };

  const setBroken = (itemId: number, broken: number) => setRejects((current) => ({
    ...current,
    [itemId]: { broken: Math.max(0, broken || 0), disposition: current[itemId]?.disposition ?? "needs_fix" },
  }));
  const setDisposition = (itemId: number, disposition: "needs_fix" | "remove") => setRejects((current) => ({
    ...current,
    [itemId]: { broken: current[itemId]?.broken ?? 0, disposition },
  }));

  return (
    <Modal open={open} onClose={onClose} title={row ? `Assign and issue request #${row.id}` : "Assign and issue"} footer={<FormFooter formId="assign-issue-form" pending={pending} submitLabel="Assign + issue" onCancel={onClose} />}>
      <form id="assign-issue-form" className="grid gap-3" onSubmit={(event) => submitForm(event, () => submitAssign())}>
        {row?.assigned_box_label ? <p className="text-xs text-muted">Box: <span className="font-medium text-ink">{row.assigned_box_label}</span></p> : null}
        <BoxCodeField value={boxCode} onChange={setBoxCode} makerspaceId={makerspaceId} pending={pending} />
        <div className="grid gap-1 text-sm">
          <span className="font-medium text-ink">Issue photo</span>
          <EvidenceUpload makerspaceId={makerspaceId} evidenceType="issue" disabled={pending} onUploaded={setEvidenceId} />
        </div>
        <label className="grid gap-1 text-sm">
          <span className="font-medium text-ink">Remark</span>
          <textarea className="desk-input min-h-20 w-full resize-y" value={remark} disabled={pending} onChange={(event) => setRemark(event.target.value)} />
        </label>
        {requiredScans > 0 ? <AssetScanList scanned={scanned} requiredScans={requiredScans} pending={pending} onScan={() => setShowScanner(true)} onRemove={(payload) => setScanned((items) => items.filter((item) => item.payload !== payload))} /> : null}
        <IssueItems row={row} pending={pending} rejects={rejects} setBroken={setBroken} setDisposition={setDisposition} />
        {showScanner ? <QrScanner onScan={handleScan} onClose={() => setShowScanner(false)} /> : null}
        <ErrorText message={validationError || error} />
      </form>
    </Modal>
  );

  function submitAssign() {
    if (!boxCode.trim()) return setValidationError("Box QR code is required.");
    if (evidenceId === null) return setValidationError("Upload an issue photo before issuing.");
    const overflow = (row?.items ?? []).find((item) => (rejects[item.id]?.broken ?? 0) > item.accepted_quantity);
    if (overflow) return setValidationError(`Can't reject more than ${overflow.accepted_quantity} of ${overflow.product_name}.`);
    if (scanned.length !== requiredScans) return setValidationError(`Scan exactly ${requiredScans} asset QR code(s) for the individually-tracked items (scanned ${scanned.length}).`);
    const rejectList = Object.entries(rejects).filter(([, value]) => value.broken > 0).map(([itemId, value]) => ({ item_id: Number(itemId), broken: value.broken, disposition: value.disposition }));
    onSubmit({ boxCode: boxCode.trim(), evidenceId, remark, rejects: rejectList, assetQrPayloads: scanned.map((item) => item.payload) });
  }
}

function AssetScanList({ scanned, requiredScans, pending, onScan, onRemove }: { scanned: ScannedAsset[]; requiredScans: number; pending: boolean; onScan: () => void; onRemove: (payload: string) => void }) {
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-ink">Scan asset QR codes ({scanned.length}/{requiredScans})</p>
        <button className="desk-button-ghost" type="button" disabled={pending} onClick={onScan}>Scan asset QR</button>
      </div>
      {scanned.length ? <div className="flex flex-wrap gap-2">{scanned.map((item) => <span key={item.payload} className="inline-flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1 text-sm text-ink">{item.label}<button className="desk-button-danger" type="button" disabled={pending} onClick={() => onRemove(item.payload)}>Remove</button></span>)}</div> : null}
    </div>
  );
}

function IssueItems({ row, pending, rejects, setBroken, setDisposition }: { row: FormModalProps<AssignIssueValues>["row"]; pending: boolean; rejects: Record<number, { broken: number; disposition: "needs_fix" | "remove" }>; setBroken: (itemId: number, broken: number) => void; setDisposition: (itemId: number, disposition: "needs_fix" | "remove") => void }) {
  return (
    <div className="grid gap-2">
      <p className="text-sm font-medium text-ink">Items - reject any broken units</p>
      {row?.items.map((item) => item.requires_asset_qr ? <div key={item.id} className="rounded-md border border-line p-2"><p className="text-sm font-medium text-ink">{item.product_name} <span className="text-muted">x{item.accepted_quantity}</span></p><ShelfLine location={item.storage_location} /><p className="mt-1 text-xs text-muted">Individually tracked - issued by asset QR scan above.</p></div> : (
        <div key={item.id} className="rounded-md border border-line p-2">
          <p className="text-sm font-medium text-ink">{item.product_name} <span className="text-muted">x{item.accepted_quantity}</span></p>
          <ShelfLine location={item.storage_location} />
          <div className="mt-2 grid gap-2 sm:grid-cols-[auto_1fr] sm:items-end">
            <label className="eyebrow grid gap-1"><span>Reject as broken</span><input className="desk-input w-24" type="number" min="0" max={item.accepted_quantity} value={rejects[item.id]?.broken ?? 0} disabled={pending} onChange={(event) => setBroken(item.id, Number(event.target.value))} /></label>
            {(rejects[item.id]?.broken ?? 0) > 0 ? <label className="eyebrow grid gap-1"><span>Send broken units to</span><select className="desk-input" value={rejects[item.id]?.disposition ?? "needs_fix"} disabled={pending} onChange={(event) => setDisposition(item.id, event.target.value as "needs_fix" | "remove")}><option value="needs_fix">To-be-fixed shelf</option><option value="remove">Remove from inventory</option></select></label> : null}
          </div>
        </div>
      ))}
    </div>
  );
}
