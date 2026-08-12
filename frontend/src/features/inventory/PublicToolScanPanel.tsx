import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Card } from "../../components/ui/Card";
import QrScanner from "../../components/ui/QrScanner";
import type { PublicToolLoan } from "../../types/inventory";
import { invalidatePublicInventory } from "../staff/queryInvalidation";
import { publicToolCheckout, publicToolReturn } from "./api";
import { PublicEvidenceUpload } from "./PublicEvidenceUpload";

type PublicToolScanPanelProps = {
  makerspaceSlug: string;
};

function LoanResult({ loan }: { loan: PublicToolLoan }) {
  return (
    <div className="rounded-xl border border-success bg-success px-3 py-2 text-on-success dark:bg-[#06281a] dark:text-[#74dd9c]">
      <p className="text-sm font-semibold capitalize">
        {loan.status.replace(/_/g, " ")}: {loan.items.map((item) => item.product_name).join(", ") || "Tool loan"}
      </p>
      <p className="mt-1 break-all text-xs">{loan.public_token}</p>
      <div className="mt-2 space-y-1">
        {loan.items.map((item) => (
          <div className="flex justify-between gap-3 text-xs" key={item.product_name}>
            <span>{item.product_name}</span>
            <span>x{item.quantity}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PublicToolScanPanel({ makerspaceSlug }: PublicToolScanPanelProps) {
  const queryClient = useQueryClient();
  const [scannedToken, setScannedToken] = useState("");
  const [scannerOpen, setScannerOpen] = useState(false);
  const [issueEvidenceId, setIssueEvidenceId] = useState<number | null>(null);
  const [returnEvidenceId, setReturnEvidenceId] = useState<number | null>(null);
  const [returnRemark, setReturnRemark] = useState("");
  const [reportProblem, setReportProblem] = useState(false);
  const [problemNote, setProblemNote] = useState("");
  const [uploadKey, setUploadKey] = useState(0);
  const effectivePayload = scannedToken.trim();
  const checkout = useMutation({
    mutationFn: () =>
      publicToolCheckout(makerspaceSlug, {
        payload: effectivePayload,
        evidence_id: issueEvidenceId as number,
      }),
    onSuccess: () => {
      invalidatePublicInventory(queryClient, makerspaceSlug);
      setIssueEvidenceId(null);
      setUploadKey((key) => key + 1);
    },
  });
  const returnTool = useMutation({
    mutationFn: () =>
      publicToolReturn(makerspaceSlug, {
        payload: effectivePayload,
        evidence_id: returnEvidenceId as number,
        remark: returnRemark.trim(),
        report_problem: reportProblem,
        problem_note: reportProblem ? problemNote.trim() : "",
      }),
    onSuccess: () => {
      invalidatePublicInventory(queryClient, makerspaceSlug);
      setReturnEvidenceId(null);
      setReturnRemark("");
      setReportProblem(false);
      setProblemNote("");
      setUploadKey((key) => key + 1);
    },
  });
  const checkoutDisabled =
    !effectivePayload ||
    issueEvidenceId === null;
  const returnDisabled =
    !effectivePayload ||
    returnEvidenceId === null ||
    !returnRemark.trim() ||
    (reportProblem && !problemNote.trim());
  const error = checkout.error?.message ?? returnTool.error?.message;
  const result = checkout.data ?? returnTool.data;

  return (
    <Card>
      <p className="text-xs font-semibold tracking-wide text-accent-ink">
        QR Tool Checkout
      </p>
      <h2 className="mt-2 text-xl font-semibold text-ink">Scan public tool</h2>
      <p className="mt-2 text-sm leading-6 text-muted">
        Upload the required photo, then scan the tool QR with your camera.
      </p>
      <button
        className="desk-button mt-4 w-full"
        type="button"
        onClick={() => setScannerOpen(true)}
      >
        Scan QR with camera
      </button>
      {scannedToken ? (
        <p className="mt-2 inline-flex items-center gap-2 rounded-lg border border-success bg-success px-3 py-1 text-sm font-semibold text-on-success dark:bg-[#06281a] dark:text-[#74dd9c]">
          Scanned OK
          <button
            type="button"
            className="text-xs font-normal underline"
            onClick={() => setScannedToken("")}
          >
            clear
          </button>
        </p>
      ) : null}
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <section className="rounded-lg border border-line p-3">
          <h3 className="text-sm font-semibold text-ink">Check out</h3>
          <div className="mt-3">
            <PublicEvidenceUpload
              key={`issue-${uploadKey}`}
              slug={makerspaceSlug}
              evidenceType="issue"
              disabled={checkout.isPending}
              onUploaded={setIssueEvidenceId}
            />
          </div>
          <button
            className="desk-button-primary mt-3 w-full disabled:cursor-not-allowed disabled:opacity-50"
            disabled={checkoutDisabled || checkout.isPending}
            type="button"
            onClick={() => checkout.mutate()}
          >
            {checkout.isPending ? "Checking out..." : "Check out"}
          </button>
        </section>
        <section className="rounded-lg border border-line p-3">
          <h3 className="text-sm font-semibold text-ink">Return</h3>
          <div className="mt-3">
            <PublicEvidenceUpload
              key={`return-${uploadKey}`}
              slug={makerspaceSlug}
              evidenceType="return"
              disabled={returnTool.isPending}
              onUploaded={setReturnEvidenceId}
            />
          </div>
          <label className="mt-3 block">
            <span className="mb-1 block text-xs font-semibold tracking-wide text-muted">
              Return condition notes
            </span>
            <textarea
              className="desk-input min-h-20 w-full"
              value={returnRemark}
              onChange={(event) => setReturnRemark(event.target.value)}
            />
          </label>
          <label className="mt-3 flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={reportProblem}
              onChange={(event) => setReportProblem(event.target.checked)}
            />
            <span>Report a problem with this tool</span>
          </label>
          {reportProblem ? (
            <label className="mt-2 block">
              <span className="mb-1 block text-xs font-semibold tracking-wide text-muted">
                What's wrong? (staff will review)
              </span>
              <textarea
                className="desk-input min-h-16 w-full"
                value={problemNote}
                onChange={(event) => setProblemNote(event.target.value)}
              />
            </label>
          ) : null}
          <button
            className="desk-button mt-3 w-full disabled:cursor-not-allowed disabled:opacity-50"
            disabled={returnDisabled || returnTool.isPending}
            type="button"
            onClick={() => returnTool.mutate()}
          >
            {returnTool.isPending ? "Returning..." : "Return"}
          </button>
        </section>
      </div>
      {error ? (
        <p className="mt-3 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
      {result ? (
        <div className="mt-3">
          <LoanResult loan={result} />
        </div>
      ) : null}
      {scannerOpen ? (
        <QrScanner
          onClose={() => setScannerOpen(false)}
          onScan={(scanned) => {
            setScannedToken(scanned);
            setScannerOpen(false);
          }}
        />
      ) : null}
    </Card>
  );
}
