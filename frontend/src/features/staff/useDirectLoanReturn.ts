import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import type { DirectLoan } from "./DirectLoanList";
import type { DirectLoanResolution } from "./DirectLoanReturnModal";
import { invalidateInventoryViews } from "./queryInvalidation";
import type { Makerspace } from "./StaffPanels";
import type { ReturnLoanPayload } from "./DirectLoansTypes";

// The return half of the direct-handout panel: its own modal state, mutation and the
// guard that refuses to submit without evidence, a remark, and (when the loan demands
// one) a return scan. Split out of DirectLoans so the container stays readable.
export function useDirectLoanReturn(makerspace: Makerspace) {
  const queryClient = useQueryClient();
  const [returningLoan, setReturningLoan] = useState<DirectLoan | null>(null);
  const [returnEvidenceId, setReturnEvidenceId] = useState<number | null>(null);
  const [returnNotes, setReturnNotes] = useState("");
  const [returnQrPayload, setReturnQrPayload] = useState("");
  useEffect(() => {
    setReturningLoan(null);
    setReturnEvidenceId(null);
    setReturnNotes("");
    setReturnQrPayload("");
  }, [makerspace.id]);
  const returnLoan = useMutation({
    mutationFn: ({ loanId, evidenceId, notes, qrPayload, resolutions }: ReturnLoanPayload) =>
      staffRequest(`/admin/direct-loans/${loanId}/return`, {
        method: "POST",
        body: JSON.stringify({ evidence_id: evidenceId, notes, qr_payload: qrPayload.trim(), resolutions }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["direct-loans", makerspace.id] });
      invalidateInventoryViews(queryClient, makerspace.id, makerspace.slug);
      resetReturnState();
    },
  });
  const resetReturnState = () => {
    setReturningLoan(null);
    setReturnEvidenceId(null);
    setReturnNotes("");
    setReturnQrPayload("");
  };
  const openReturnModal = (loan: DirectLoan) => {
    returnLoan.reset();
    setReturningLoan(loan);
    setReturnEvidenceId(null);
    setReturnNotes("");
    setReturnQrPayload("");
  };
  const closeReturnModal = () => {
    if (returnLoan.isPending) return;
    returnLoan.reset();
    resetReturnState();
  };
  const submitReturn = (resolutions: DirectLoanResolution[]) => {
    if (!returningLoan || returnEvidenceId === null || !returnNotes.trim()) return;
    if (returningLoan.return_scan_required && !returnQrPayload.trim()) return;
    returnLoan.mutate({
      loanId: returningLoan.id,
      evidenceId: returnEvidenceId,
      notes: returnNotes.trim(),
      qrPayload: returnQrPayload,
      resolutions,
    });
  };
  return {
    returningLoan,
    returnEvidenceId,
    returnNotes,
    returnQrPayload,
    pending: returnLoan.isPending,
    error: returnLoan.error?.message ?? "",
    setReturnEvidenceId,
    setReturnNotes,
    setReturnQrPayload,
    openReturnModal,
    closeReturnModal,
    submitReturn,
  };
}
