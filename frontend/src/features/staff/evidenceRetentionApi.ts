import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";

export type EvidenceRetentionPolicy = {
  makerspace_id: number;
  platform_default_days: number;
  override_days: number | null;
  effective_days: number;
  object_expiry_enabled: boolean;
};

export type EvidenceRetentionPreview = {
  as_of: string;
  policy_days: number;
  cutoff: string;
  object_candidates: number;
  candidate_bytes: number;
  has_more: boolean;
};

const pathFor = (makerspaceId: number) =>
  `/admin/makerspaces/${makerspaceId}/evidence-retention`;

export const evidenceRetentionKeys = {
  policy: (makerspaceId: number) => ["evidence-retention", makerspaceId] as const,
  preview: (makerspaceId: number, days: number) =>
    ["evidence-retention", makerspaceId, "preview", days] as const,
};

export function useEvidenceRetentionPolicy(makerspaceId: number) {
  return useQuery({
    queryKey: evidenceRetentionKeys.policy(makerspaceId),
    queryFn: () => staffRequest<EvidenceRetentionPolicy>(pathFor(makerspaceId)),
  });
}

export function useEvidenceRetentionPreview(
  makerspaceId: number,
  effectiveDays: number,
  enabled: boolean,
) {
  return useQuery({
    queryKey: evidenceRetentionKeys.preview(makerspaceId, effectiveDays),
    queryFn: () => staffRequest<EvidenceRetentionPreview>(
      `${pathFor(makerspaceId)}/preview`,
      { method: "POST", body: JSON.stringify({ limit: 100 }) },
    ),
    enabled,
  });
}

export function useUpdateEvidenceRetention(makerspaceId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (objectRetentionDays: number | null) =>
      staffRequest<EvidenceRetentionPolicy>(pathFor(makerspaceId), {
        method: "PATCH",
        body: JSON.stringify({ object_retention_days: objectRetentionDays }),
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: evidenceRetentionKeys.policy(makerspaceId),
        }),
        queryClient.invalidateQueries({
          queryKey: ["evidence-retention", makerspaceId, "preview"],
        }),
        queryClient.invalidateQueries({ queryKey: ["audit"] }),
      ]);
    },
  });
}
