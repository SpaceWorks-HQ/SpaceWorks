import { useState } from "react";

import { Panel } from "./shared";
import {
  useMemberCards,
  usePrintCard,
  usePrintSheet,
  useReissueCard,
  useRevokeCard,
} from "./memberCards/api";
import { CardsTable } from "./memberCards/CardsTable";
import { CardTemplateForm } from "./memberCards/CardTemplateForm";
import { ReissueCardDialog, RevokeCardDialog } from "./memberCards/CardDialogs";
import { IssueRoster } from "./memberCards/IssueRoster";
import { ScanCardBox } from "./memberCards/ScanCardBox";
import type { CardStatus, MemberCard, ReissueReason } from "./memberCards/types";

const STATUSES: CardStatus[] = ["active", "revoked"];
const STATUS_LABELS: Record<CardStatus, string> = { active: "Active", revoked: "Revoked" };

/** Member ID cards: issue, print, reissue, revoke, plus the front-desk scan lookup.
 *
 *  Gated by the `membership` module in staffTabs.TAB_MODULES — a card belongs to a
 *  membership, so without that module every endpoint here 404s.
 */
export function MemberCardsPanel({ makerspaceId }: { makerspaceId: number }) {
  const [status, setStatus] = useState<CardStatus>("active");
  const [selected, setSelected] = useState<number[]>([]);
  const [reissueTarget, setReissueTarget] = useState<MemberCard | null>(null);
  const [reissueReason, setReissueReason] = useState<ReissueReason>("lost");
  const [revokeTarget, setRevokeTarget] = useState<MemberCard | null>(null);
  const [revokeReason, setRevokeReason] = useState("");

  const cards = useMemberCards(makerspaceId, status);
  const activeCards = useMemberCards(makerspaceId, "active");
  const printCard = usePrintCard();
  const printSheet = usePrintSheet(makerspaceId);
  const reissue = useReissueCard(makerspaceId);
  const revoke = useRevokeCard(makerspaceId);

  const rows = cards.data?.results ?? [];
  const cardedMembershipIds = (activeCards.data?.results ?? [])
    .map((card) => card.membership_id)
    .filter((id): id is number => id !== null);
  const printError = printCard.error ?? printSheet.error;

  return (
    <Panel title="Member cards">
      <div className="grid gap-4">
        <p className="text-sm text-muted">
          Printed CR80 cards for this makerspace&apos;s members. Prints are counted, and a
          revoked card stops resolving at the door.
        </p>

        <div className="flex flex-wrap items-center gap-3">
          <div className="desk-actions flex flex-wrap gap-2" role="group" aria-label="Card status">
            {STATUSES.map((value) => (
              <button
                key={value}
                type="button"
                className={value === status ? "desk-button-primary" : "desk-button-ghost"}
                aria-pressed={value === status}
                onClick={() => {
                  setStatus(value);
                  setSelected([]);
                }}
              >
                {STATUS_LABELS[value]}
              </button>
            ))}
          </div>
          <button
            className="desk-button ml-auto"
            type="button"
            disabled={printSheet.isPending}
            onClick={() => printSheet.mutate(selected)}
          >
            {printSheet.isPending
              ? "Preparing…"
              : selected.length
                ? `Print sheet (${selected.length} selected)`
                : "Print sheet (all active)"}
          </button>
        </div>

        {cards.error ? (
          <p className="text-sm text-danger" role="alert">
            {cards.error instanceof Error ? cards.error.message : "Could not load member cards."}
          </p>
        ) : null}
        {printError ? (
          <p className="text-sm text-danger" role="alert">
            {printError instanceof Error ? printError.message : "Could not build that PDF."}
          </p>
        ) : null}

        <CardsTable
          cards={rows}
          status={status}
          loading={cards.isLoading}
          selectedIds={selected}
          onSelectionChange={setSelected}
          printingCardId={printCard.isPending ? (printCard.variables?.id ?? null) : null}
          onPrint={(card) => printCard.mutate(card)}
          onReissue={(card) => {
            setReissueReason("lost");
            setReissueTarget(card);
          }}
          onRevoke={(card) => {
            setRevokeReason("");
            setRevokeTarget(card);
          }}
        />

        <ScanCardBox makerspaceId={makerspaceId} />
        <IssueRoster makerspaceId={makerspaceId} cardedMembershipIds={cardedMembershipIds} />
        <CardTemplateForm makerspaceId={makerspaceId} />
      </div>

      <ReissueCardDialog
        card={reissueTarget}
        reason={reissueReason}
        pending={reissue.isPending}
        error={reissue.error instanceof Error ? reissue.error.message : undefined}
        onReasonChange={setReissueReason}
        onClose={() => setReissueTarget(null)}
        onSubmit={() => {
          if (!reissueTarget) return;
          reissue.mutate(
            { cardId: reissueTarget.id, reason: reissueReason },
            { onSuccess: () => setReissueTarget(null) },
          );
        }}
      />
      <RevokeCardDialog
        card={revokeTarget}
        reason={revokeReason}
        pending={revoke.isPending}
        error={revoke.error instanceof Error ? revoke.error.message : undefined}
        onReasonChange={setRevokeReason}
        onClose={() => setRevokeTarget(null)}
        onSubmit={() => {
          if (!revokeTarget) return;
          revoke.mutate(
            { cardId: revokeTarget.id, reason: revokeReason.trim() || undefined },
            { onSuccess: () => setRevokeTarget(null) },
          );
        }}
      />
    </Panel>
  );
}
