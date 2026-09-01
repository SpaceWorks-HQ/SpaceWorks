import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { DetailDrawer } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { EvidenceUpload } from "../panels/EvidenceUpload";
import { DialogError, submit } from "./shared";
import type { DialogProps } from "./types";

export function IssueDialog({ row, makerspace, onClose }: DialogProps) {
  const queryClient = useQueryClient();
  const [evidenceId, setEvidenceId] = useState<number | null>(null);
  const [remark, setRemark] = useState("");
  const [assetInputs, setAssetInputs] = useState<Record<string, string>>({});
  const individualItems = row.items.filter((item) => item.tracking_mode === "individual");
  const assetFields = individualItems.flatMap((item) =>
    Array.from({ length: item.accepted_quantity }, (_, index) => ({
      key: `${item.id}-${index}`,
      label: `${item.product_name} unit ${index + 1} asset QR`,
    })),
  );
  const requiredAssetCount = individualItems.reduce((total, item) => total + item.accepted_quantity, 0);
  const assetQrPayloads = assetFields.map((field) => assetInputs[field.key]?.trim() ?? "").filter(Boolean);
  const mutation = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/requests/${row.id}/issue`, {
        method: "POST",
        body: JSON.stringify({
          evidence_id: evidenceId,
          remark: remark.trim(),
          asset_qr_payloads: assetQrPayloads,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries();
      onClose();
    },
  });
  const canSubmit = Boolean(evidenceId) && assetQrPayloads.length === requiredAssetCount;

  return (
    <DetailDrawer open title={`Issue request #${row.id}`} onClose={onClose}>
      <form
        className="grid gap-4 text-sm"
        onSubmit={(event) => submit(event, () => {
          if (canSubmit) mutation.mutate();
        })}
      >
        {row.assigned_box_code ? (
          <p className="rounded-md border border-line bg-surface px-3 py-2 text-muted">
            Assigned box: <span className="font-medium text-ink">{row.assigned_box_code}</span>
          </p>
        ) : (
          <p className="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-warn">
            No box is assigned to this request.
          </p>
        )}
        <EvidenceUpload
          makerspaceId={makerspace.id}
          evidenceType="issue"
          label="Evidence photo"
          onUploaded={setEvidenceId}
        />
        <label className="grid gap-1">
          <span className="font-medium text-ink">Remark</span>
          <textarea
            className="desk-input min-h-24"
            value={remark}
            onChange={(event) => setRemark(event.target.value)}
          />
        </label>
        {individualItems.length ? (
          <div className="grid gap-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Asset QR codes</h3>
            {assetFields.map((field) => (
              <label className="grid gap-1" key={field.key}>
                <span className="font-medium text-ink">{field.label}</span>
                <input
                  className="desk-input"
                  value={assetInputs[field.key] ?? ""}
                  onChange={(event) =>
                    setAssetInputs((current) => ({
                      ...current,
                      [field.key]: event.target.value,
                    }))
                  }
                />
              </label>
            ))}
          </div>
        ) : null}
        <DialogError error={mutation.error} />
        <div className="desk-actions flex flex-wrap justify-end gap-2">
          <button className="desk-button" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="desk-button" type="submit" disabled={!canSubmit || mutation.isPending}>
            Issue
          </button>
        </div>
      </form>
    </DetailDrawer>
  );
}
