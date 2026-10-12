import { useContext, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Modal } from "../../../components/ui";
import QrScanner from "../../../components/ui/QrScanner";
import { staffRequest } from "../../../lib/api";
import { featureEnabled } from "../../../lib/features";
import { KitChecklistCapture, useKitChecklist } from "../../inventory/KitChecklist";
import { StaffListContext } from "../StaffListContext";
import { useResolveCard } from "../panels/memberCards/api";
import { EvidenceUpload } from "../panels/EvidenceUpload";
import { useStaffGet, type Makerspace } from "../panels/shared";
import type { DirectLoanMemberResponse, ProductOption, QrResolveResponse } from "../DirectLoansTypes";

export function DirectHandoverWizard({ makerspace, onClose }: { makerspace: Makerspace; onClose: () => void }) {
  const client = useQueryClient();
  const authority = useContext(StaffListContext);
  const canScanCard = authority.isSuperadmin || authority.actions?.includes("scan_member_cards");
  const [step, setStep] = useState(0);
  const [borrower, setBorrower] = useState("");
  const [cardPayload, setCardPayload] = useState("");
  const [scanning, setScanning] = useState<"card" | "items" | null>(null);
  const [payloads, setPayloads] = useState<string[]>([]);
  const [qrInput, setQrInput] = useState("");
  const [selected, setSelected] = useState<Record<number, string>>({});
  const [evidence, setEvidence] = useState<number | null>(null);
  const [remark, setRemark] = useState("");
  const [scanError, setScanError] = useState("");
  const [receipt, setReceipt] = useState<{ id: number; at: string; borrower: string; labels: string[] } | null>(null);
  const members = useStaffGet<DirectLoanMemberResponse>(["direct-loan-members", makerspace.id], `/admin/makerspace/${makerspace.id}/direct-loan-members?page_size=1000`);
  const products = useStaffGet<{ results: ProductOption[] }>(["inventory-all", makerspace.id], `/admin/makerspace/${makerspace.id}/inventory?page_size=1000`);
  const memberRows = Array.isArray(members.data) ? members.data : members.data?.results ?? [];
  const productRows = (products.data?.results ?? []).filter(row => !row.is_archived && row.available_quantity > 0);
  const items = Object.entries(selected).filter(([, count]) => count !== "" && Number(count) > 0).map(([id, count]) => ({ product_id: Number(id), quantity: Number(count) }));
  const quantitiesValid = Object.entries(selected).every(([id, count]) => count === "" || (Number.isInteger(Number(count)) && Number(count) >= 0 && Number(count) <= (productRows.find(row => row.id === Number(id))?.available_quantity ?? 0)));
  const card = useResolveCard(makerspace.id);
  const kits = useKitChecklist(`/admin/makerspace/${makerspace.id}/kit-checklist-preview`, { phase: "issue", qr_payloads: payloads, items, container_id: null }, featureEnabled(makerspace.enabled_features ?? [], "loans.kit_checklist") && Boolean(items.length || payloads.length) && quantitiesValid);
  const itemsReady = Boolean(items.length || payloads.length) && quantitiesValid;
  const ready = Boolean(borrower && itemsReady && evidence && kits.ready);
  const issue = useMutation({
    mutationFn: () => {
      if (!ready) throw new Error("Choose a borrower and eligible tools, then upload an issue photo.");
      return staffRequest<{ id: number }>(`/admin/makerspace/${makerspace.id}/direct-loans`, { method: "POST", body: JSON.stringify({ borrower_id: Number(borrower), evidence_id: evidence, remark: remark.trim(), qr_payloads: payloads, items, kit_checklist: kits.counts }) });
    },
    onSuccess: result => { setReceipt({ id: result.id, at: new Date().toLocaleString(), borrower: memberRows.find(row => String(row.user_id) === borrower)?.display_name ?? borrower, labels: items.map(item => `${productRows.find(row => row.id === item.product_id)?.name ?? item.product_id} × ${item.quantity}`) }); setStep(3); void client.invalidateQueries(); },
  });
  async function scanCard(payload: string) {
    setBorrower(""); setScanError("");
    try {
      const result = await card.mutateAsync(payload);
      const member = result.outcome === "ok" ? memberRows.find(row => row.membership_id === result.membership_id) : undefined;
      if (!member) throw new Error("This card does not identify an eligible borrower here. Select a verified member or ask a manager.");
      setBorrower(String(member.user_id)); setScanning(null);
    } catch (cause) { setScanError(cause instanceof Error ? cause.message : "Card could not be checked."); }
  }
  async function scanItem(payload: string) {
    const value = payload.trim(); if (!value) return;
    try {
      const result = await staffRequest<QrResolveResponse & { qr: { makerspace: number }; allowed_actions: string[] }>("/admin/qr/resolve", { method: "POST", body: JSON.stringify({ payload: value }) });
      if (result.qr?.makerspace !== makerspace.id) throw new Error("Scan a tool from this makerspace.");
      if (result.target.type === "box") throw new Error("Scan a tool or asset QR in this flow.");
      if (!result.allowed_actions?.includes("direct_handout")) throw new Error("This tool is unavailable for direct handout.");
      setPayloads(previous => previous.includes(value) ? previous : [...previous, value]); setScanError("");
    } catch (cause) { setScanError(cause instanceof Error ? cause.message : "Tool QR could not be checked."); }
  }
  return <Modal open title="Guided direct handout" onClose={() => { if (!issue.isPending) onClose(); }} footer={<div className="sticky bottom-0 grid grid-cols-2 gap-2 bg-panel">
    <button className="desk-button-ghost min-h-11" disabled={issue.isPending} onClick={onClose}>{receipt ? "Close receipt" : "Cancel"}</button>
    {receipt ? <button className="desk-button" onClick={() => window.print()}>Print receipt</button> : step < 2 ? <button className="desk-button-primary min-h-11" disabled={step === 0 ? !borrower : !itemsReady} onClick={() => { setStep(step + 1); setScanError(""); }}>Next</button> : <button className="desk-button-success min-h-11" disabled={!ready || issue.isPending} onClick={() => issue.mutate()}>{issue.isPending ? "Saving…" : "Confirm handout"}</button>}
  </div>}>
    <p role="status" className="mb-3">Step {step + 1} of 4: {["Borrower card", "Scan or select tools", "Issue photo", "Receipt"][step]}</p>
    {step > 0 && !receipt ? <button className="desk-button-ghost mb-3" disabled={issue.isPending} onClick={() => setStep(step - 1)}>Back</button> : null}
    <fieldset className="grid gap-3" disabled={issue.isPending}><legend className="sr-only">Handout details</legend>
      {step === 0 ? <>
        {canScanCard ? <><button className="desk-button" onClick={() => setScanning("card")}>Scan member card</button><label>Card payload<input className="desk-input block" value={cardPayload} onChange={event => setCardPayload(event.target.value)} /></label><button className="desk-button" disabled={!cardPayload.trim() || card.isPending} onClick={() => void scanCard(cardPayload)}>Check card</button></> : null}
        <label>Borrower<select className="desk-input block w-full" value={borrower} onChange={event => setBorrower(event.target.value)}><option value="">Choose an active member</option>{memberRows.map(row => <option key={row.user_id} value={row.user_id}>{row.display_name || row.username}</option>)}</select></label>
      </> : null}
      {step === 1 ? <>
        <button className="desk-button" onClick={() => setScanning("items")}>Scan tools continuously</button><label>Tool QR payload<input className="desk-input block w-full" value={qrInput} onChange={event => setQrInput(event.target.value)} /></label><button className="desk-button" disabled={!qrInput.trim()} onClick={() => void scanItem(qrInput)}>Check tool QR</button>
        <ul>{payloads.map(value => <li key={value} className="flex flex-wrap gap-2 break-all">{value}<button className="desk-button-ghost" onClick={() => setPayloads(payloads.filter(payload => payload !== value))}>Remove</button></li>)}</ul>
        {productRows.filter(row => row.tracking_mode !== "individual").map(row => <label key={row.id} className="grid gap-1">{row.name}<input className="desk-input" type="number" min="0" step="1" max={row.available_quantity} value={selected[row.id] ?? ""} onChange={event => setSelected({ ...selected, [row.id]: event.target.value })} /></label>)}
      </> : null}
      {step === 2 ? <><EvidenceUpload makerspaceId={makerspace.id} evidenceType="issue" onUploaded={setEvidence} />{evidence ? <p>Uploaded photo #{evidence}</p> : null}<label className="grid gap-1">Issue remark<textarea className="desk-input" value={remark} onChange={event => setRemark(event.target.value)} /></label><KitChecklistCapture checklist={kits} /></> : null}
      {receipt ? <div role="status"><h3 className="title-section">Handout #{receipt.id} recorded</h3><p>{receipt.borrower} · {receipt.at}</p>{receipt.labels.map((label, index) => <p key={index}>{label}</p>)}<p>{payloads.length} tool QR scans · Evidence photo #{evidence}</p>{remark ? <p>{remark}</p> : null}</div> : null}
    </fieldset>
    {members.error || products.error || issue.error || scanError ? <p role="alert" className="mt-3 text-danger">{scanError || (issue.error ?? members.error ?? products.error)?.message}</p> : null}
    {scanning ? <QrScanner feedback={<><p role="status">{scanning === "items" ? `${payloads.length} tools scanned` : "Check borrower card"}</p>{scanError ? <p role="alert">{scanError}</p> : null}</>} onScan={payload => { if (scanning === "card") { if (!card.isPending) void scanCard(payload); } else void scanItem(payload); }} onClose={() => setScanning(null)} /> : null}
  </Modal>;
}
