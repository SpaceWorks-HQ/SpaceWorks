import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Card } from "../../components/ui/Card";
import type { RequestCartItem } from "../../types/inventory";
import { BorrowRequestCard } from "./BorrowRequestCard";
import { submitPublicRequest } from "./api";
import { invalidatePublicInventory } from "../staff/queryInvalidation";
import { PublicToolScanPanel } from "./PublicToolScanPanel";

type ActiveTab = "borrow" | "scan";

type PublicRequestPanelProps = {
  items: RequestCartItem[];
  makerspaceSlug: string;
  onClear: () => void;
  disabled?: boolean;
};

export function PublicRequestPanel({
  items,
  makerspaceSlug,
  onClear,
  disabled = false,
}: PublicRequestPanelProps) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<ActiveTab>("borrow");
  const [requestedFor, setRequestedFor] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const totalItems = useMemo(
    () => items.reduce((total, item) => total + item.quantity, 0),
    [items],
  );

  const submitMutation = useMutation({
    mutationFn: () =>
      submitPublicRequest(makerspaceSlug, {
        requested_for: requestedFor.trim(),
        items: items.map((item) => ({
          product_id: item.productId,
          quantity: item.quantity,
        })),
      }),
    onSuccess: (response) => {
      invalidatePublicInventory(queryClient, makerspaceSlug);
      void response;
      setSubmitted(true);
      onClear();
    },
  });

  // Each tab carries its own palette tone - a touch of colour so the action row
  // doesn't read as flat. Active = filled pastel (+ dark deep-tint); idle = neutral
  // with a faint tone hover hint.
  const tabTone: Record<ActiveTab, { active: string; idle: string }> = {
    borrow: {
      active:
        "border-secondary bg-secondary text-on-secondary dark:bg-secondary/15 dark:text-secondary-ink",
      idle: "hover:border-secondary hover:bg-secondary/15 hover:text-secondary-ink",
    },
    scan: {
      active:
        "border-secondary bg-secondary text-on-secondary dark:bg-secondary/15 dark:text-secondary-ink",
      idle: "hover:border-secondary hover:bg-secondary/15 hover:text-secondary-ink",
    },
  };

  function tabClass(tab: ActiveTab) {
    const tone = tabTone[tab];
    return activeTab === tab
      ? `status-box min-h-11 w-full py-2 shadow-soft ${tone.active}`
      : `status-box min-h-11 w-full py-2 ${tone.idle}`;
  }

  const canSubmit =
    requestedFor.trim().length > 0 &&
    items.length > 0 &&
    !submitMutation.isPending;

  return (
    <aside className="space-y-4 lg:sticky lg:top-0 lg:max-h-[100dvh] lg:flex lg:flex-col lg:overflow-hidden">
      {disabled ? (
        <Card>
          <p className="eyebrow text-secondary-ink">
            Requests
          </p>
          <h2 className="title-panel mt-2">Unavailable</h2>
          <p className="mt-2 text-sm text-muted">
            This makerspace is publishing inventory without public requests.
          </p>
        </Card>
      ) : (
        <>
          <Card className="shrink-0" padding="sm">
            <h2 className="title-panel text-secondary-ink">
              Member borrowing
            </h2>
            <p className="mt-2 text-sm text-muted">
              Requests use your signed-in member account. An active membership, waiver acceptance, and current presence are required.
            </p>
          </Card>

          <div
            aria-label="Request actions"
            className="grid shrink-0 grid-cols-2 gap-2"
          >
            <button
              aria-pressed={activeTab === "borrow"}
              className={tabClass("borrow")}
              id="public-request-borrow-tab"
              type="button"
              onClick={() => setActiveTab("borrow")}
            >
              Borrow request
            </button>
            <button
              aria-pressed={activeTab === "scan"}
              className={tabClass("scan")}
              id="public-request-scan-tab"
              type="button"
              onClick={() => setActiveTab("scan")}
            >
              Scan a tool
            </button>
          </div>

          <div className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
            {activeTab === "borrow" ? (
              <div
                id="public-request-borrow-panel"
              >
                <BorrowRequestCard
                  canSubmit={canSubmit}
                  items={items}
                  requestedFor={requestedFor}
                  submitError={submitMutation.error?.message}
                  submitPending={submitMutation.isPending}
                  submitted={submitted}
                  totalItems={totalItems}
                  onClear={onClear}
                  onRequestedForChange={setRequestedFor}
                  onSubmit={() => submitMutation.mutate()}
                />
              </div>
            ) : null}

            {activeTab === "scan" ? (
              <div
                aria-labelledby="public-request-scan-tab"
                id="public-request-scan-panel"
                role="tabpanel"
              >
                <PublicToolScanPanel
                  makerspaceSlug={makerspaceSlug}
                />
              </div>
            ) : null}
          </div>
        </>
      )}
    </aside>
  );
}
