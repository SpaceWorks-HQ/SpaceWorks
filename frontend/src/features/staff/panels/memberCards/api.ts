import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest, staffRequestBlob } from "../../../../lib/api";
import type {
  CardMembershipRow,
  CardResolveResult,
  CardStatus,
  CardTemplate,
  MemberCard,
  MemberCardPage,
  ReissueReason,
} from "./types";

export const memberCardKeys = {
  list: (makerspaceId: number, status: CardStatus) =>
    ["member-cards", makerspaceId, status] as const,
  template: (makerspaceId: number) => ["member-card-template", makerspaceId] as const,
};

const base = (makerspaceId: number) => `/admin/makerspaces/${makerspaceId}/member-cards`;

/** Hand the blob to the browser as a download. Object URLs leak until revoked. */
export function downloadPdf(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function useMemberCards(makerspaceId: number, status: CardStatus) {
  return useQuery({
    queryKey: memberCardKeys.list(makerspaceId, status),
    queryFn: () => staffRequest<MemberCardPage>(`${base(makerspaceId)}?status=${status}`),
  });
}

export function useCardMemberships(makerspaceId: number) {
  return useQuery({
    queryKey: ["staff", "memberships", makerspaceId],
    queryFn: () =>
      staffRequest<CardMembershipRow[]>(`/admin/makerspaces/${makerspaceId}/memberships`),
  });
}

/** Every mutation invalidates BOTH status lists: a revoke moves a row from one to the
 *  other, so refreshing only the visible tab leaves the other tab stale on the next
 *  switch (and the roster's "no active card" set with it). */
function useCardMutation<TVars>(
  makerspaceId: number,
  mutationFn: (vars: TVars) => Promise<MemberCard>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: memberCardKeys.list(makerspaceId, "active") }),
        client.invalidateQueries({ queryKey: memberCardKeys.list(makerspaceId, "revoked") }),
      ]),
  });
}

export function useIssueCard(makerspaceId: number) {
  return useCardMutation(
    makerspaceId,
    ({ membershipId, printedName }: { membershipId: number; printedName?: string }) =>
      staffRequest<MemberCard>(`${base(makerspaceId)}/${membershipId}/issue`, {
        method: "POST",
        body: JSON.stringify(printedName ? { printed_name: printedName } : {}),
      }),
  );
}

export function useReissueCard(makerspaceId: number) {
  return useCardMutation(
    makerspaceId,
    ({ cardId, reason }: { cardId: number; reason: ReissueReason }) =>
      staffRequest<MemberCard>(`/admin/member-cards/${cardId}/reissue`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
  );
}

export function useRevokeCard(makerspaceId: number) {
  return useCardMutation(
    makerspaceId,
    ({ cardId, reason }: { cardId: number; reason?: string }) =>
      staffRequest<MemberCard>(`/admin/member-cards/${cardId}/revoke`, {
        method: "POST",
        body: JSON.stringify(reason ? { reason } : {}),
      }),
  );
}

export function usePrintCard() {
  return useMutation({
    mutationFn: async (card: MemberCard) => {
      const blob = await staffRequestBlob(`/admin/member-cards/${card.id}/print.pdf`, {
        method: "POST",
      });
      downloadPdf(blob, `member-card-${card.card_number}.pdf`);
    },
  });
}

export function usePrintSheet(makerspaceId: number) {
  return useMutation({
    mutationFn: async (cardIds: number[]) => {
      const blob = await staffRequestBlob(`${base(makerspaceId)}.pdf`, {
        method: "POST",
        body: JSON.stringify({ preset: "sheet", ...(cardIds.length ? { card_ids: cardIds } : {}) }),
      });
      downloadPdf(blob, `member-cards-${makerspaceId}.pdf`);
    },
  });
}

/** Scan results are deliberately a mutation, not a query: a lookup of a physical token
 *  must not be cached and replayed as if the card were still in front of the operator. */
export function useResolveCard(makerspaceId: number) {
  return useMutation({
    mutationFn: (payload: string) =>
      staffRequest<CardResolveResult>(`${base(makerspaceId)}/resolve`, {
        method: "POST",
        body: JSON.stringify({ payload: payload.trim() }),
      }),
  });
}

export function useCardTemplate(makerspaceId: number) {
  return useQuery({
    queryKey: memberCardKeys.template(makerspaceId),
    queryFn: () =>
      staffRequest<CardTemplate>(`/admin/makerspaces/${makerspaceId}/member-card-template`),
  });
}

export function useSaveCardTemplate(makerspaceId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (template: CardTemplate) =>
      staffRequest<CardTemplate>(`/admin/makerspaces/${makerspaceId}/member-card-template`, {
        method: "PUT",
        body: JSON.stringify(template),
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: memberCardKeys.template(makerspaceId) }),
  });
}
