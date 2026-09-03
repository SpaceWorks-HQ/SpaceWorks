import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import QrScanner from "../../components/ui/QrScanner";
import { Pagination } from "../../components/ui/Pagination";
import { staffRequest } from "../../lib/api";
import { usePaginatedQuery } from "../../lib/usePaginatedQuery";
import { DirectLoanList, type DirectLoan } from "./DirectLoanList";
import { invalidateInventoryViews } from "./queryInvalidation";
import { DirectLoanReturnModal } from "./DirectLoanReturnModal";
import { Panel, type Makerspace, useStaffGet } from "./StaffPanels";
import { MemberClaimCodes } from "./MemberClaimCodes";
import {
  DirectLoanBorrowerFields,
  DirectLoanContainerField,
  DirectLoanIssueEvidence,
  DirectLoanItemLines,
  DirectLoanQrSection,
} from "./DirectLoanIssueFields";
import { useDirectLoanReturn } from "./useDirectLoanReturn";
import {
  labelForTarget,
  type ContainerResponse,
  type DirectLoanMemberResponse,
  type LineDraft,
  type ProductOption,
  type QrResolveResponse,
  type ScannedPayload,
} from "./DirectLoansTypes";

export function DirectLoans({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const [borrowerId, setBorrowerId] = useState("");
  const [lineRows, setLineRows] = useState<LineDraft[]>([{ key: 1, productId: "", quantity: "1" }]);
  const [nextLineKey, setNextLineKey] = useState(2);
  const [scanned, setScanned] = useState<ScannedPayload[]>([]);
  const [showScanner, setShowScanner] = useState(false);
  const [qrPayloads, setQrPayloads] = useState("");
  const [containerId, setContainerId] = useState("");
  const [showContainerScanner, setShowContainerScanner] = useState(false);
  const [containerScanError, setContainerScanError] = useState("");
  const [issueEvidenceId, setIssueEvidenceId] = useState<number | null>(null);
  const [issueRemark, setIssueRemark] = useState("Issued from direct handout.");
  const [issueUploadKey, setIssueUploadKey] = useState(0);
  useEffect(() => {
    setBorrowerId("");
    setLineRows([{ key: 1, productId: "", quantity: "1" }]);
    setNextLineKey(2);
    setScanned([]);
    setShowScanner(false);
    setQrPayloads("");
    setContainerId("");
    setShowContainerScanner(false);
    setContainerScanError("");
    setIssueEvidenceId(null);
    setIssueRemark("Issued from direct handout.");
    setIssueUploadKey((key) => key + 1);
  }, [makerspace.id]);
  const returnFlow = useDirectLoanReturn(makerspace);
  const products = useStaffGet<{ results: ProductOption[] }>(
    ["inventory-all", makerspace.id],
    `/admin/makerspace/${makerspace.id}/inventory?page_size=1000`,
  );
  // Fetch ALL containers (distinct cache key from the shared ["containers"] entry so a
  // truncated first page can't leak in): the dropdown + the scan membership check both
  // need the complete list, else a valid container past page one falsely reads as "not found".
  const containers = useStaffGet<ContainerResponse>(
    ["containers-all", makerspace.id],
    `/admin/makerspace/${makerspace.id}/containers?page_size=1000`,
  );
  // The endpoint is a DRF ListAPIView, so it answers with the paginated envelope, not a
  // bare array — the same unwrap `containerOptions` below already does. Typing it as an
  // array made `.map` a runtime TypeError that took the whole panel down with it.
  const members = useStaffGet<DirectLoanMemberResponse>(
    ["direct-loan-members", makerspace.id],
    `/admin/makerspace/${makerspace.id}/direct-loan-members?page_size=1000`,
  );
  const memberOptions = Array.isArray(members.data)
    ? members.data
    : members.data?.results ?? [];
  const containerOptions = Array.isArray(containers.data)
    ? containers.data
    : containers.data?.results ?? [];
  const activeProducts = (products.data?.results ?? []).filter((product) => !product.is_archived);
  const productById = new Map(activeProducts.map((product) => [product.id, product]));
  const loans = usePaginatedQuery<DirectLoan>({
    key: ["direct-loans", makerspace.id],
    path: `/admin/makerspace/${makerspace.id}/direct-loans`,
    resetKey: String(makerspace.id),
  });
  const issue = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/makerspace/${makerspace.id}/direct-loans`, {
        method: "POST",
        body: JSON.stringify({
          borrower_id: Number(borrowerId),
          evidence_id: issueEvidenceId as number,
          remark: issueRemark.trim(),
          container_id: containerId ? Number(containerId) : null,
          qr_payloads: Array.from(new Set([
            ...scanned.map((item) => item.payload),
            ...pastedQrPayloads,
          ])),
          items: validManualLines
            .map((line) => ({ product_id: Number(line.productId), quantity: Number(line.quantity) })),
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["direct-loans", makerspace.id] });
      invalidateInventoryViews(queryClient, makerspace.id, makerspace.slug);
      setLineRows([{ key: 1, productId: "", quantity: "1" }]);
      setNextLineKey(2);
      setScanned([]);
      setQrPayloads("");
      setContainerId("");
      setShowContainerScanner(false);
      setContainerScanError("");
      setIssueEvidenceId(null);
      setIssueRemark("Issued from direct handout.");
      setIssueUploadKey((key) => key + 1);
    },
  });
  const pastedQrPayloads = qrPayloads.split("\n").map((value) => value.trim()).filter(Boolean);
  const validManualLines = lineRows.filter((line) => {
    const product = productById.get(Number(line.productId));
    return Boolean(product) && product?.tracking_mode !== "individual" && Number(line.quantity) > 0;
  });
  const hasIssueContent =
    validManualLines.length > 0 || scanned.length > 0 || pastedQrPayloads.length > 0 || Boolean(containerId);
  const canIssue =
    Boolean(borrowerId) &&
    hasIssueContent &&
    issueEvidenceId !== null &&
    !issue.isPending;
  const addLine = () => {
    setLineRows((rows) => [...rows, { key: nextLineKey, productId: "", quantity: "1" }]);
    setNextLineKey((key) => key + 1);
  };
  const updateLine = (key: number, patch: Partial<LineDraft>) => {
    setLineRows((rows) => rows.map((line) => (line.key === key ? { ...line, ...patch } : line)));
  };
  const removeLine = (key: number) => {
    setLineRows((rows) => rows.filter((line) => line.key !== key));
  };
  const removeScanned = (payload: string) => {
    setScanned((items) => items.filter((item) => item.payload !== payload));
  };
  const handleScan = async (payload: string) => {
    const cleanPayload = payload.trim();
    if (!cleanPayload || scanned.some((item) => item.payload === cleanPayload)) return;
    let label = cleanPayload;
    try {
      const result = await staffRequest<QrResolveResponse>("/admin/qr/resolve", {
        method: "POST",
        body: JSON.stringify({ payload: cleanPayload }),
      });
      label = labelForTarget(result.target, cleanPayload);
    } catch {
      label = cleanPayload;
    }
    setScanned((items) =>
      items.some((item) => item.payload === cleanPayload)
        ? items
        : [...items, { payload: cleanPayload, label }],
    );
  };
  const handleContainerScan = async (payload: string) => {
    try {
      const result = await staffRequest<QrResolveResponse>("/admin/qr/resolve", {
        method: "POST",
        body: JSON.stringify({ payload }),
      });
      const target = result.target;
      if (target.type !== "box") {
        setContainerScanError("Scanned QR is not a container.");
        return;
      }
      if (!containerOptions.some((container) => container.id === target.id)) {
        setContainerScanError("That container isn't available for handout (inactive or not found).");
        return;
      }
      setContainerId(String(target.id));
      setContainerScanError("");
    } catch {
      setContainerScanError("Could not resolve the scanned QR.");
    } finally {
      setShowContainerScanner(false);
    }
  };

  return (
    <div className="grid gap-4">
      <Panel title="Direct handout">
        <DirectLoanBorrowerFields
          makerspaceId={makerspace.id}
          borrowerId={borrowerId}
          onBorrowerIdChange={setBorrowerId}
          memberOptions={memberOptions}
          membersLoading={members.isLoading}
          membersError={members.error?.message}
        />
        <DirectLoanContainerField
          containerId={containerId}
          onContainerIdChange={setContainerId}
          containerOptions={containerOptions}
          containersLoading={containers.isLoading}
          scanError={containerScanError}
          onScanClick={() => {
            setContainerScanError("");
            setShowContainerScanner(true);
          }}
        />
        <DirectLoanItemLines
          lineRows={lineRows}
          activeProducts={activeProducts}
          productById={productById}
          productsLoading={products.isLoading}
          onAdd={addLine}
          onUpdate={updateLine}
          onRemove={removeLine}
        />
        <DirectLoanQrSection
          scanned={scanned}
          qrPayloads={qrPayloads}
          onOpenScanner={() => setShowScanner(true)}
          onRemoveScanned={removeScanned}
          onQrPayloadsChange={setQrPayloads}
        />
        <DirectLoanIssueEvidence
          uploadKey={issueUploadKey}
          makerspaceId={makerspace.id}
          disabled={issue.isPending}
          onUploaded={setIssueEvidenceId}
          remark={issueRemark}
          onRemarkChange={setIssueRemark}
        />
        {issueEvidenceId === null ? <p className="mt-3 text-sm text-muted">Upload an issue photo before issuing.</p> : null}
        {!hasIssueContent ? <p className="mt-3 text-sm text-muted">Add at least one item, QR payload, or container before issuing.</p> : null}
        <button className="desk-button-primary mt-3" disabled={!canIssue} onClick={() => issue.mutate()}>
          Issue direct handout
        </button>
        {issue.error ? <p className="mt-3 text-sm text-danger">{issue.error.message}</p> : null}
        {products.error ? <p className="mt-3 text-sm text-danger">{products.error.message}</p> : null}
        {containers.error ? <p className="mt-3 text-sm text-danger">{containers.error.message}</p> : null}
        {showScanner ? <QrScanner onScan={handleScan} onClose={() => setShowScanner(false)} /> : null}
        {showContainerScanner ? <QrScanner onScan={handleContainerScan} onClose={() => setShowContainerScanner(false)} /> : null}
      </Panel>
      <MemberClaimCodes makerspaceId={makerspace.id} members={memberOptions} />
      <DirectLoanList loans={loans.results} onReturn={returnFlow.openReturnModal} />
      <Pagination page={loans.page} totalPages={loans.totalPages} onChange={loans.setPage} count={loans.count} pageSize={loans.pageSize} />
      <DirectLoanReturnModal
        loan={returnFlow.returningLoan}
        makerspaceId={makerspace.id}
        evidenceId={returnFlow.returnEvidenceId}
        notes={returnFlow.returnNotes}
        qrPayload={returnFlow.returnQrPayload}
        pending={returnFlow.pending}
        error={returnFlow.error}
        onEvidenceUploaded={returnFlow.setReturnEvidenceId}
        onNotesChange={returnFlow.setReturnNotes}
        onQrPayloadChange={returnFlow.setReturnQrPayload}
        onCancel={returnFlow.closeReturnModal}
        onSubmit={returnFlow.submitReturn}
      />
    </div>
  );
}
