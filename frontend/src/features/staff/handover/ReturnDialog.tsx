import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { DetailDrawer } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { EvidenceUpload } from "../panels/EvidenceUpload";
import {
  defaultReturnValues,
  DialogError,
  parseReturnValues,
  QuantityInput,
  remainingQuantity,
  submit,
  updateReturnValue,
  valuesAreValid,
} from "./shared";
import type { DialogProps, ReturnValues } from "./types";

export function ReturnDialog({ row, makerspace, onClose }: DialogProps) {
  const queryClient = useQueryClient();
  const [evidenceId, setEvidenceId] = useState<number | null>(null);
  const [boxCode, setBoxCode] = useState(row.assigned_box_code ?? "");
  const [remark, setRemark] = useState("");
  const [values, setValues] = useState<Record<number, ReturnValues>>(() => defaultReturnValues(row));
  const rows = useMemo(
    () =>
      row.items.map((item) => {
        const remaining = remainingQuantity(item);
        const value = values[item.id] ?? { returned: "0", damaged: "0", missing: "0" };
        const parsed = parseReturnValues(value);
        const total = parsed.returned + parsed.damaged + parsed.missing;
        return {
          item,
          remaining,
          value,
          parsed,
          total,
          valid: valuesAreValid(parsed) && total <= remaining,
        };
      }),
    [row, values],
  );
  const resolutions = rows
    .map(({ item, parsed }) => ({ item_id: item.id, ...parsed }))
    .filter((resolution) => resolution.returned + resolution.damaged + resolution.missing > 0);
  const hasInvalidRow = rows.some((returnRow) => !returnRow.valid);
  const mutation = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/requests/${row.id}/return`, {
        method: "POST",
        body: JSON.stringify({
          evidence_id: evidenceId,
          box_code: boxCode.trim(),
          remark: remark.trim(),
          resolutions,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries();
      onClose();
    },
  });
  const canSubmit = Boolean(evidenceId) && Boolean(remark.trim()) && resolutions.length > 0 && !hasInvalidRow;

  useEffect(() => {
    setEvidenceId(null);
    setBoxCode(row.assigned_box_code ?? "");
    setRemark("");
    setValues(defaultReturnValues(row));
  }, [row]);

  return (
    <DetailDrawer open title={`Return request #${row.id}`} onClose={onClose}>
      <form
        className="grid gap-4 text-sm"
        onSubmit={(event) => submit(event, () => {
          if (canSubmit) mutation.mutate();
        })}
      >
        <EvidenceUpload
          makerspaceId={makerspace.id}
          evidenceType="return"
          label="Evidence photo"
          onUploaded={setEvidenceId}
        />
        <label className="grid gap-1">
          <span className="font-medium text-ink">Box QR code</span>
          <input className="desk-input" value={boxCode} onChange={(event) => setBoxCode(event.target.value)} />
        </label>
        <div className="grid gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Return quantities</h3>
          {rows.map(({ item, remaining, value, total, valid }) => (
            <div key={item.id} className="grid gap-2 rounded-md border border-line bg-surface p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium text-ink">{item.product_name}</span>
                <span className="text-xs text-muted">Remaining {remaining}</span>
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                <QuantityInput
                  label="Returned"
                  value={value.returned}
                  onChange={(next) => updateReturnValue(setValues, item.id, "returned", next)}
                />
                <QuantityInput
                  label="Damaged"
                  value={value.damaged}
                  onChange={(next) => updateReturnValue(setValues, item.id, "damaged", next)}
                />
                <QuantityInput
                  label="Missing"
                  value={value.missing}
                  onChange={(next) => updateReturnValue(setValues, item.id, "missing", next)}
                />
              </div>
              {!valid ? (
                <p className="text-xs text-danger">
                  Row total must be between 0 and {remaining}. Current total: {total}.
                </p>
              ) : null}
            </div>
          ))}
        </div>
        <label className="grid gap-1">
          <span className="font-medium text-ink">Remark</span>
          <textarea
            className="desk-input min-h-24"
            required
            value={remark}
            onChange={(event) => setRemark(event.target.value)}
          />
        </label>
        <DialogError error={mutation.error} />
        <div className="desk-actions flex flex-wrap justify-end gap-2">
          <button className="desk-button" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="desk-button" type="submit" disabled={!canSubmit || mutation.isPending}>
            Return
          </button>
        </div>
      </form>
    </DetailDrawer>
  );
}
