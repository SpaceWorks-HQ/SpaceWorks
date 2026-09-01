import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Card } from "../../components/ui/Card";
import type { RequestCartItem } from "../../types/inventory";
import { BorrowRequestCard } from "./BorrowRequestCard";
import { getAccessToken, refreshAccessToken } from "../../lib/api";
import { submitPublicRequest } from "./api";
import { invalidatePublicInventory } from "../staff/queryInvalidation";
import { PublicToolScanPanel } from "./PublicToolScanPanel";

type ActiveTab = "borrow" | "scan";

type PublicRequestPanelProps = {
  items: RequestCartItem[];
  makerspaceSlug: string;
  onClear: () => void;
  disabled?: boolean;
  // The makerspace's policy, not the caller's state. Present only when the space opted
  // into account-less borrow requests.
  requestAccess?: "anyone";
};

// The header is required for account-less submissions, and it is what makes a retry
// idempotent: the same key with the same payload returns the original request. Held for
// the lifetime of one composed request and rotated only after a successful submit, so a
// network retry of the SAME attempt cannot create a second request.
function newIdempotencyKey() {
  const cryptoRef = globalThis.crypto;
  if (cryptoRef && typeof cryptoRef.randomUUID === "function") {
    return cryptoRef.randomUUID();
  }
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

export function PublicRequestPanel({
  items,
  makerspaceSlug,
  onClear,
  disabled = false,
  requestAccess,
}: PublicRequestPanelProps) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<ActiveTab>("borrow");
  const [requestedFor, setRequestedFor] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [contactName, setContactName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [website, setWebsite] = useState("");
  const [publicToken, setPublicToken] = useState("");
  const idempotencyKey = useRef(newIdempotencyKey());
  // A signed-in member who RELOADED this page holds no in-memory access token -- it lives
  // behind the refresh cookie, and unlike `MemberArea` this page never hydrates. Without
  // the probe they would be classified as anonymous and their request filed against the
  // SHARED anonymous principal, which every per-person view excludes: it would vanish from
  // their own activity and take the unverified-contact path instead of notifying them.
  const sessionProbe = useQuery({
    queryKey: ["public-request-session", makerspaceSlug],
    queryFn: async () => (getAccessToken() ? true : refreshAccessToken()),
    enabled: requestAccess === "anyone" && !disabled,
    staleTime: Infinity,
    retry: false,
  });
  // Policy AND caller state. `tenantPublicRequest` still attaches Authorization when a
  // token is in memory, and the backend then takes the AUTHENTICATED branch and ignores
  // these contact fields -- so asking for them would promise something the stored request
  // does not honour. Until the probe settles we assume a member: claiming "no account
  // needed" and then discovering a session would be the worse way round.
  const authenticated = Boolean(getAccessToken());
  const accountLess =
    requestAccess === "anyone" && sessionProbe.isFetched && !authenticated;
  const totalItems = useMemo(
    () => items.reduce((total, item) => total + item.quantity, 0),
    [items],
  );

  const submitMutation = useMutation({
    mutationFn: () =>
      submitPublicRequest(
        makerspaceSlug,
        {
          requested_for: requestedFor.trim(),
          items: items.map((item) => ({
            product_id: item.productId,
            quantity: item.quantity,
          })),
          website,
          ...(accountLess
            ? {
                contact_name: contactName.trim(),
                contact_email: contactEmail.trim(),
                contact_phone: contactPhone.trim(),
              }
            : {}),
        },
        accountLess ? idempotencyKey.current : undefined,
      ),
    // The previous banner and token must not survive into the next attempt: if this one
    // fails, showing the error beside a stale token invites the requester to save the
    // wrong reference -- and it is their only route back to the request.
    onMutate: () => {
      setSubmitted(false);
      setPublicToken("");
    },
    onSuccess: (response) => {
      invalidatePublicInventory(queryClient, makerspaceSlug);
      // Kept before the form is cleared: this token is the account-less requester's only
      // way back to the request.
      setPublicToken(response?.public_token ?? "");
      setSubmitted(true);
      onClear();
      setContactName("");
      setContactEmail("");
      setContactPhone("");
      setRequestedFor("");
      setWebsite("");
      // Only after the server accepted it: reusing the key for the NEXT request would
      // return this one back instead of creating anything.
      idempotencyKey.current = newIdempotencyKey();
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

  const contactReady =
    !accountLess ||
    (contactName.trim().length > 0 && contactEmail.trim().length > 0);
  // While the probe is unresolved `accountLess` is still false, so `contactReady` is
  // vacuously true and the button would go live before the contact fields exist. On a
  // slow refresh a visitor could submit a member-shaped body and take a 400.
  const policyResolved = requestAccess !== "anyone" || sessionProbe.isFetched;
  const canSubmit =
    requestedFor.trim().length > 0 &&
    items.length > 0 &&
    contactReady &&
    policyResolved &&
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
              {accountLess && activeTab === "borrow"
                ? "Borrow something"
                : "Member borrowing"}
            </h2>
            <p className="mt-2 text-sm text-muted">
              {/* Three states, because the requirements genuinely differ. Scoped to the
                  borrow tab: scanning a tool is self-checkout, which DOES require an
                  authenticated member with active presence, so "no account needed" would
                  be false there until it 401s. And an `anyone` policy necessarily has the
                  membership module off, so the membership/waiver/presence sentence cannot
                  be true on such a space even for a signed-in visitor. */}
              {activeTab === "borrow" && accountLess
                ? "No account needed. Leave your name and email so staff can reach you about the request; they review it before anything is handed over."
                : activeTab === "borrow" && requestAccess === "anyone"
                  ? "You are signed in, so this request is filed against your account. Staff review it before anything is handed over."
                  : "Requests use your signed-in member account. An active membership, waiver acceptance, and current presence are required."}
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
                  accountLess={accountLess}
                  contactName={contactName}
                  contactEmail={contactEmail}
                  contactPhone={contactPhone}
                  onContactNameChange={setContactName}
                  onContactEmailChange={setContactEmail}
                  onContactPhoneChange={setContactPhone}
                  website={website}
                  onWebsiteChange={setWebsite}
                  publicToken={publicToken}
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
