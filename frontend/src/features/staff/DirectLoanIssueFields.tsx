import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { EvidenceUpload } from "./panels/EvidenceUpload";
import { WalkInMemberForm } from "./WalkInMemberForm";
import type {
  ContainerOption,
  DirectLoanMember,
  LineDraft,
  ProductOption,
  ScannedPayload,
} from "./DirectLoansTypes";

export function DirectLoanBorrowerFields({
  makerspaceId,
  borrowerId,
  onBorrowerIdChange,
  memberOptions,
  membersLoading,
  membersError,
}: {
  makerspaceId: number;
  borrowerId: string;
  onBorrowerIdChange: (value: string) => void;
  memberOptions: DirectLoanMember[];
  membersLoading: boolean;
  membersError?: string;
}) {
  const queryClient = useQueryClient();
  const selectedMember = memberOptions.find(
    (member) => String(member.user_id) === borrowerId,
  );
  const witnessWaiver = useMutation({
    mutationFn: () => {
      if (!selectedMember) throw new Error("Select a member first.");
      return staffRequest(
        `/admin/memberships/${selectedMember.membership_id}/waiver/witness`,
        { method: "POST", body: JSON.stringify({}) },
      );
    },
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ["members", makerspaceId],
    }),
  });
  return (
    <>
      <label className="block text-sm font-medium text-ink" htmlFor="direct-loan-borrower">
        Borrowing member
      </label>
      <select
        id="direct-loan-borrower"
        className="desk-input mt-1 w-full"
        value={borrowerId}
        disabled={membersLoading}
        onChange={(event) => {
          onBorrowerIdChange(event.target.value);
          witnessWaiver.reset();
        }}
      >
        <option value="">Select an active member</option>
        {memberOptions.map((member) => (
          <option key={member.user_id} value={member.user_id}>
            {member.display_name || member.username}
          </option>
        ))}
      </select>
      {membersError ? <p className="mt-2 text-sm text-danger">{membersError}</p> : null}
      {selectedMember ? (
        <button
          className="desk-button mt-2"
          type="button"
          disabled={witnessWaiver.isPending}
          onClick={() => witnessWaiver.mutate()}
        >
          Record witnessed waiver acceptance
        </button>
      ) : null}
      {witnessWaiver.isSuccess ? <p className="mt-2 text-sm text-success-ink">Waiver acceptance recorded.</p> : null}
      {witnessWaiver.error ? <p className="mt-2 text-sm text-danger">{witnessWaiver.error.message}</p> : null}
      <WalkInMemberForm
        makerspaceId={makerspaceId}
        onCreated={(userId) => onBorrowerIdChange(String(userId))}
      />
    </>
  );
}

export function DirectLoanContainerField({
  containerId,
  onContainerIdChange,
  containerOptions,
  containersLoading,
  scanError,
  onScanClick,
}: {
  containerId: string;
  onContainerIdChange: (value: string) => void;
  containerOptions: ContainerOption[];
  containersLoading: boolean;
  scanError: string;
  onScanClick: () => void;
}) {
  return (
    <>
      <label className="mt-4 block text-sm font-medium text-ink" htmlFor="direct-loan-container">Container (optional)</label>
      <div className="mt-1 flex flex-col gap-2 md:flex-row">
        <select
          id="direct-loan-container"
          className="desk-input w-full"
          value={containerId}
          disabled={containersLoading}
          onChange={(e) => onContainerIdChange(e.target.value)}
        >
          <option value="">No container</option>
          {containerOptions.map((container) => (
            <option key={container.id} value={container.id}>{container.label}</option>
          ))}
        </select>
        <button
          type="button"
          className="desk-button"
          onClick={onScanClick}
        >
          Scan container
        </button>
      </div>
      {scanError ? <p className="mt-1 text-sm text-danger">{scanError}</p> : null}
    </>
  );
}

export function DirectLoanItemLines({
  lineRows,
  activeProducts,
  productById,
  productsLoading,
  onAdd,
  onUpdate,
  onRemove,
}: {
  lineRows: LineDraft[];
  activeProducts: ProductOption[];
  productById: Map<number, ProductOption>;
  productsLoading: boolean;
  onAdd: () => void;
  onUpdate: (key: number, patch: Partial<LineDraft>) => void;
  onRemove: (key: number) => void;
}) {
  return (
    <div className="mt-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="title-section">Items</h3>
        <button className="desk-button" type="button" onClick={onAdd}>Add item</button>
      </div>
      <div className="grid gap-2">
        {lineRows.map((line) => {
          const selectedLineProduct = productById.get(Number(line.productId));
          const selectedIndividual = selectedLineProduct?.tracking_mode === "individual";
          return (
            <div key={line.key} className="grid gap-2 md:grid-cols-[1fr_120px_auto]">
              <select aria-label="Product" className="desk-input" value={line.productId} disabled={productsLoading} onChange={(e) => onUpdate(line.key, { productId: e.target.value })}>
                <option value="">Inventory item</option>
                {activeProducts.map((product) => (
                  <option key={product.id} value={product.id}>
                    {product.name} | {product.tracking_mode} | {product.available_quantity} available
                    {product.storage_location ? ` - Shelf: ${product.storage_location}` : ""}
                  </option>
                ))}
              </select>
              <input aria-label="Quantity" className="desk-input" min={1} inputMode="numeric" type="number" value={line.quantity} disabled={selectedIndividual} onChange={(e) => onUpdate(line.key, { quantity: e.target.value })} />
              <button className="desk-button" type="button" onClick={() => onRemove(line.key)}>Remove</button>
              {selectedLineProduct ? <p className="font-mono text-xs uppercase text-muted md:col-span-3">{selectedLineProduct.tracking_mode}{selectedIndividual ? " | scan unit QR" : ""}</p> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function DirectLoanQrSection({
  scanned,
  qrPayloads,
  onOpenScanner,
  onRemoveScanned,
  onQrPayloadsChange,
}: {
  scanned: ScannedPayload[];
  qrPayloads: string;
  onOpenScanner: () => void;
  onRemoveScanned: (payload: string) => void;
  onQrPayloadsChange: (value: string) => void;
}) {
  return (
    <>
      <div className="mt-4">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h3 className="title-section">QR payloads</h3>
          <button className="desk-button" type="button" onClick={onOpenScanner}>Scan QR</button>
        </div>
        {scanned.length ? (
          <div className="mb-3 flex flex-wrap gap-2">
            {scanned.map((item) => (
              <span key={item.payload} className="inline-flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1 text-sm text-ink">
                {item.label}
                <button className="desk-button-ghost px-2 text-danger" type="button" onClick={() => onRemoveScanned(item.payload)}>Remove</button>
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <textarea
        aria-label="QR payloads"
        className="desk-input mt-3 h-24 w-full font-mono text-sm"
        placeholder="Optional QR payloads, one per line"
        value={qrPayloads}
        onChange={(e) => onQrPayloadsChange(e.target.value)}
      />
    </>
  );
}

export function DirectLoanIssueEvidence({
  uploadKey,
  makerspaceId,
  disabled,
  onUploaded,
  remark,
  onRemarkChange,
}: {
  uploadKey: number;
  makerspaceId: number;
  disabled: boolean;
  onUploaded: (evidenceId: number | null) => void;
  remark: string;
  onRemarkChange: (value: string) => void;
}) {
  return (
    <div className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr]">
      <EvidenceUpload
        key={uploadKey}
        makerspaceId={makerspaceId}
        evidenceType="issue"
        disabled={disabled}
        onUploaded={onUploaded}
      />
      <label className="block">
        <span className="eyebrow mb-1 block">
          Issue remark
        </span>
        <textarea
          className="desk-input min-h-20 w-full"
          value={remark}
          onChange={(event) => onRemarkChange(event.target.value)}
        />
      </label>
    </div>
  );
}
