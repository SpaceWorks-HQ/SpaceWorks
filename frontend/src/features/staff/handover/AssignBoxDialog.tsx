import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { DetailDrawer } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { DialogError, submit } from "./shared";
import type { DialogProps } from "./types";

export function AssignBoxDialog({ row, onClose }: DialogProps) {
  const queryClient = useQueryClient();
  const [boxCode, setBoxCode] = useState(row.assigned_box_code ?? "");
  const mutation = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/requests/${row.id}/assign-box`, {
        method: "POST",
        body: JSON.stringify({ box_code: boxCode.trim() }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries();
      onClose();
    },
  });

  return (
    <DetailDrawer open title={`Assign box #${row.id}`} onClose={onClose}>
      <form
        className="grid gap-4 text-sm"
        onSubmit={(event) => submit(event, () => {
          if (boxCode.trim()) mutation.mutate();
        })}
      >
        <label className="grid gap-1">
          <span className="font-medium text-ink">Box QR code</span>
          <input
            className="desk-input"
            value={boxCode}
            onChange={(event) => setBoxCode(event.target.value)}
            autoFocus
          />
        </label>
        <DialogError error={mutation.error} />
        <div className="desk-actions flex flex-wrap justify-end gap-2">
          <button className="desk-button" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="desk-button" type="submit" disabled={!boxCode.trim() || mutation.isPending}>
            Assign box
          </button>
        </div>
      </form>
    </DetailDrawer>
  );
}
