import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Modal } from "../../../components/ui";
import QrScanner from "../../../components/ui/QrScanner";
import { staffRequest } from "../../../lib/api";
import { featureEnabled } from "../../../lib/features";
import { KitChecklistCapture, useKitChecklist } from "../../inventory/KitChecklist";
import { EvidenceUpload } from "../panels/EvidenceUpload";
import type { HardwareRequest } from "../panels/Queues";
import type { Makerspace } from "../panels/shared";
import { ScanCardBox } from "../panels/memberCards/ScanCardBox";
import { HandoverBoxScan } from "./HandoverBoxScan";
import { HandoverItems, initialResolutions, validResolutions } from "./HandoverItems";

const steps = ["Scan container", "Check borrower card", "Check items", "Photo and confirmation", "Receipt"];
export function HandoverWizard({ row, makerspace, mode, canScanCards = false, onClose }: {
  row: HardwareRequest; makerspace: Makerspace; mode: "issue" | "return"; canScanCards?: boolean; onClose: () => void;
}) {
  const client = useQueryClient();
  const [step, setStep] = useState(0);
  const [boxCode, setBoxCode] = useState("");
  const [borrowerChecked, setBorrowerChecked] = useState(false);
  const [evidence, setEvidence] = useState<number | null>(null);
  const [remark, setRemark] = useState("");
  const [resolutions, setResolutions] = useState(() => initialResolutions(row));
  const [assets, setAssets] = useState<string[]>([]);
  const [scanner, setScanner] = useState(false);
  const [assetInput, setAssetInput] = useState("");
  const [scanError, setScanError] = useState("");
  const [boxAssigned, setBoxAssigned] = useState(false);
  const [receiptAt, setReceiptAt] = useState("");
  const finalResolutions = resolutions.filter(value => value.returned + value.damaged + value.missing > 0);
  const requiredAssets = row.items.filter(item => item.requires_asset_qr).reduce((count, item) => count + item.accepted_quantity, 0);
  const itemsReady = mode === "issue" ? assets.length === requiredAssets : validResolutions(row, resolutions);
  const kitEnabled = mode === "issue" ? featureEnabled(makerspace.enabled_features ?? [], "loans.kit_checklist") : Boolean(row.has_kit_checklist);
  const kits = useKitChecklist(`/admin/makerspace/${makerspace.id}/kit-checklist-preview`,
    { request_id: row.id, phase: mode, box_code: boxCode, ...(mode === "return" ? { resolutions: finalResolutions } : {}) }, kitEnabled && Boolean(boxCode) && itemsReady);
  const ready = Boolean(boxCode && borrowerChecked && evidence && itemsReady && kits.ready && (mode !== "return" || remark.trim()));
  const mutation = useMutation({
    mutationFn: async () => {
      if (!ready) throw new Error("Complete the scan, borrower, items and photo steps first.");
      if (mode === "issue") {
        await staffRequest(`/admin/requests/${row.id}/assign-box`, { method: "POST", body: JSON.stringify({ box_code: boxCode }) });
        setBoxAssigned(true);
        await staffRequest(`/admin/requests/${row.id}/issue`, { method: "POST", body: JSON.stringify({ evidence_id: evidence, remark: remark.trim(), asset_qr_payloads: assets, kit_checklist: kits.counts }) });
      } else {
        await staffRequest(`/admin/requests/${row.id}/return`, { method: "POST", body: JSON.stringify({ evidence_id: evidence, box_code: boxCode, remark: remark.trim(), resolutions: finalResolutions, kit_checklist: kits.counts }) });
      }
    },
    onSuccess: () => { setReceiptAt(new Date().toLocaleString()); setStep(4); void client.invalidateQueries(); },
    onError: () => { void client.invalidateQueries(); },
  });
  async function scanAsset(payload: string) {
    const clean = payload.trim(); if (!clean || assets.includes(clean)) return;
    try {
      const result = await staffRequest<{ qr: { makerspace: number }; target: { type: string; status?: string } }>("/admin/qr/resolve", { method: "POST", body: JSON.stringify({ payload: clean }) });
      if (result.qr?.makerspace !== makerspace.id) throw new Error("Scan an asset from this makerspace.");
      if (result.target.type !== "asset") throw new Error("Scan an individual asset QR.");
      if (result.target.status !== "available") throw new Error("This asset is unavailable for issue.");
      setAssets(previous => previous.includes(clean) ? previous : [...previous, clean]); setScanError("");
    } catch (cause) { setScanError(cause instanceof Error ? cause.message : "Asset QR could not be checked."); }
  }
  const nextReady = step === 0 ? Boolean(boxCode) : step === 1 ? borrowerChecked : itemsReady;
  return <Modal open title={`${mode === "issue" ? "Issue" : "Return"} request #${row.id}`} onClose={() => { if (!mutation.isPending) onClose(); }} footer={<div className="sticky bottom-0 grid grid-cols-2 gap-2 bg-panel">
    <button className="desk-button-ghost min-h-11" type="button" disabled={mutation.isPending} onClick={onClose}>{step === 4 ? "Close receipt" : "Cancel"}</button>
    {step === 4 ? <button className="desk-button min-h-11" type="button" onClick={() => window.print()}>Print receipt</button> : step < 3 ? <button className="desk-button-primary min-h-11" disabled={!nextReady} type="button" onClick={() => setStep(step + 1)}>Next</button> : <button className="desk-button-success min-h-11" type="button" disabled={!ready || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? "Saving…" : `Confirm ${mode}`}</button>}
  </div>}>
    <p role="status" className="mb-3 text-sm">Step {step + 1} of 5: {steps[step]}</p>
    {step > 0 && step < 4 ? <button className="desk-button-ghost mb-3" disabled={mutation.isPending} onClick={() => setStep(step - 1)}>Back</button> : null}
    <fieldset className="grid gap-3" disabled={mutation.isPending}><legend className="sr-only">{steps[step]}</legend>
      {step === 0 ? <HandoverBoxScan code={boxCode} onCode={setBoxCode} makerspaceId={makerspace.id} /> : null}
      {step === 1 ? <><p>Borrower: <strong>{row.requester_display || row.requester_username}</strong></p>{canScanCards ? <ScanCardBox makerspaceId={makerspace.id} /> : null}<label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={borrowerChecked} onChange={event => setBorrowerChecked(event.target.checked)} />I checked the borrower against this request</label></> : null}
      {step === 2 ? <><HandoverItems row={row} mode={mode} resolutions={resolutions} onChange={setResolutions} />{mode === "issue" && requiredAssets > 0 ? <>
        <p>Individual assets: {assets.length} / {requiredAssets}</p><button className="desk-button" type="button" onClick={() => setScanner(true)}>Scan items continuously</button>
        <label>Asset QR payload<input className="desk-input block w-full" value={assetInput} onChange={event => setAssetInput(event.target.value)} /></label><button className="desk-button" disabled={!assetInput.trim()} type="button" onClick={() => void scanAsset(assetInput)}>Check asset QR</button>
        <ul>{assets.map(payload => <li key={payload} className="flex flex-wrap gap-2 break-all">{payload}<button className="desk-button-ghost" type="button" onClick={() => setAssets(assets.filter(value => value !== payload))}>Remove</button></li>)}</ul>{scanError ? <p role="alert">{scanError}</p> : null}
      </> : null}{!itemsReady ? <p role="status">Check all quantities and required asset scans before continuing.</p> : null}</> : null}
      {step === 3 ? <><EvidenceUpload makerspaceId={makerspace.id} evidenceType={mode} onUploaded={setEvidence} />{evidence ? <p>Uploaded photo #{evidence}</p> : null}<label className="grid gap-1">{mode === "return" ? "Return remark (required)" : "Issue remark"}<textarea className="desk-input" value={remark} onChange={event => setRemark(event.target.value)} /></label><KitChecklistCapture checklist={kits} /><p>Request #{row.id} · Container {boxCode}. Confirm only after checking the photo and all items.</p></> : null}
      {step === 4 ? <div role="status"><h3 className="title-section">{mode === "issue" ? "Issue" : "Return"} recorded</h3><p>Request #{row.id} · {receiptAt}</p><p>Evidence photo #{evidence} · Container {boxCode}</p>{row.items.map(item => {
        const resolution = finalResolutions.find(value => value.item_id === item.id);
        return <p key={item.id}>{item.product_name}: {mode === "issue" ? `${item.accepted_quantity} issued` : resolution ? `${resolution.returned} returned, ${resolution.damaged} damaged, ${resolution.missing} missing` : "No return recorded in this handover"}</p>;
      })}{remark ? <p>{remark}</p> : null}</div> : null}
    </fieldset>
    {mutation.error ? <p role="alert" className="mt-3 text-danger">{boxAssigned && mode === "issue" ? "Box assignment was recorded; issue still needs to complete. " : ""}{mutation.error.message}</p> : null}
    {scanner ? <QrScanner feedback={<><p role="status">Individual assets: {assets.length} / {requiredAssets}</p>{scanError ? <p role="alert">{scanError}</p> : null}</>} onScan={payload => void scanAsset(payload)} onClose={() => setScanner(false)} /> : null}
  </Modal>;
}
