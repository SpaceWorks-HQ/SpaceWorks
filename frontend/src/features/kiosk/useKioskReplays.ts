import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";
import { invalidateRequestQueues } from "../staff/panels/QueuesInvalidation";
import type { ReplayEnvelope } from "./kioskReplayApi";

export type ReplayResolutionCode = "acknowledged_no_change" | "replaced_online";
export type RecoveryReplay = {
  id: string; makerspace_id: number; station_id: number; station_name: string; station_kind: string;
  operator_display: string; operation_kind: ReplayEnvelope["kind"]; operation_version: number;
  aggregate_id: string; sequence: number; state: "failed";
  created_at: string; client_created_at: string; completed_at: string; expires_at: string; retained_until: string;
  failure_code: string; failure_detail: string;
  subject_request_id: number | null; subject_loan_id: number | null;
  recovery_request_id: number | null; recovery_loan_id: number | null;
  result_request_id: number | null; result_loan_id: number | null; result_return_event_id: number | null;
  predecessor_id: string | null; predecessor_state: string | null;
  evidence_id: number | null; can_view_evidence: boolean;
  resolution_code: ReplayResolutionCode | null; resolved_at: string | null;
  resolved_by_display: string | null; replacement_command_id: string | null;
};
export type RecoveryPage = { count: number; next: string | null; previous: string | null; results: RecoveryReplay[] };
export const recoveryPath = (id: string) => `/admin/kiosk-replays/${encodeURIComponent(id)}/`;

export function useKioskReplays(makerspaceId: number, resolution: string, page: number) {
  return useQuery({
    queryKey: ["kiosk-replays", makerspaceId, resolution, page],
    queryFn: () => staffRequest<RecoveryPage>(`/admin/makerspace/${makerspaceId}/kiosk-replays/?resolution=${resolution}&page=${page}`),
  });
}

export function useReplayDetail(id: string | null) {
  return useQuery({ queryKey: ["kiosk-replay", id], enabled: Boolean(id),
    queryFn: () => staffRequest<RecoveryReplay>(recoveryPath(id!)) });
}

export function useResolveReplay(makerspaceId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; resolution_code: ReplayResolutionCode; replacement_command_id?: string }) =>
      staffRequest<RecoveryReplay>(`${recoveryPath(id)}resolve/`, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (row) => {
      void client.invalidateQueries({ queryKey: ["kiosk-replays", makerspaceId] });
      void client.invalidateQueries({ queryKey: ["kiosk-replay", row.id] });
      invalidateRequestQueues(client, makerspaceId, { inventory: true, needsFix: true, ledger: true });
      void client.invalidateQueries({ queryKey: ["direct-loans", makerspaceId] });
    },
  });
}
