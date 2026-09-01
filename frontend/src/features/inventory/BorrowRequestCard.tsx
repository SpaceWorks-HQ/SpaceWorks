import { Card } from "../../components/ui/Card";
import type { RequestCartItem } from "../../types/inventory";

type BorrowRequestCardProps = {
  canSubmit: boolean;
  items: RequestCartItem[];
  requestedFor: string;
  submitError?: string;
  submitPending: boolean;
  submitted: boolean;
  totalItems: number;
  onClear: () => void;
  onRequestedForChange: (value: string) => void;
  onSubmit: () => void;
  // Account-less mode: the makerspace opted into requests without an account, so the
  // borrower has no profile to read a name and email from and must supply them here.
  accountLess?: boolean;
  contactName?: string;
  contactEmail?: string;
  contactPhone?: string;
  onContactNameChange?: (value: string) => void;
  onContactEmailChange?: (value: string) => void;
  onContactPhoneChange?: (value: string) => void;
  // Honeypot, carried by every other public form (booking, printing, events). A bot that
  // autofills it gets the server's decoy response instead of a real request.
  website?: string;
  onWebsiteChange?: (value: string) => void;
  // The ONLY handle an account-less requester has on their request: their contact details
  // are unverified so no lifecycle email is sent, and status lookup is by token.
  publicToken?: string;
};

export function BorrowRequestCard({
  canSubmit,
  items,
  requestedFor,
  submitError,
  submitPending,
  submitted,
  totalItems,
  onClear,
  onRequestedForChange,
  onSubmit,
  accountLess = false,
  contactName = "",
  contactEmail = "",
  contactPhone = "",
  onContactNameChange,
  onContactEmailChange,
  onContactPhoneChange,
  website = "",
  onWebsiteChange,
  publicToken,
}: BorrowRequestCardProps) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow text-secondary-ink">
            Borrow Request
          </p>
          <h2 className="title-panel mt-2">
            Selected equipment
          </h2>
        </div>
        <span className="rounded-lg border border-secondary bg-secondary/15 px-3 py-1 font-mono text-sm font-semibold text-secondary-ink">
          {totalItems}
        </span>
      </div>

      {items.length === 0 ? (
        <p className="mt-4 text-sm leading-6 text-muted">
          {accountLess
            ? "Add public items from the inventory list, then leave your name and email to submit the request."
            : "Add public items from the inventory list, then submit the request with your signed-in member account."}
        </p>
      ) : (
        <div className="mt-4 space-y-2">
          <div className="max-h-40 space-y-2 overflow-y-auto">
            {items.map((item) => (
              <div
                className="flex items-center justify-between gap-3 rounded-lg border border-line bg-surface px-3 py-2"
                key={item.productId}
              >
                <span className="text-sm font-medium text-ink">{item.name}</span>
                <span className="font-mono text-sm text-muted">x{item.quantity}</span>
              </div>
            ))}
          </div>
          <button className="desk-button w-full" type="button" onClick={onClear}>
            Clear selection
          </button>
        </div>
      )}

      <div className="mt-5 space-y-3">
        {accountLess ? (
          <div className="space-y-3">
            <label className="block">
              <span className="eyebrow mb-1 block">Your name</span>
              <input
                autoComplete="name"
                className="desk-input w-full"
                maxLength={200}
                placeholder="Ada Lovelace"
                type="text"
                value={contactName}
                onChange={(event) => onContactNameChange?.(event.target.value)}
              />
            </label>
            <label className="block">
              <span className="eyebrow mb-1 block">Email</span>
              <input
                autoComplete="email"
                className="desk-input w-full"
                maxLength={254}
                placeholder="you@example.com"
                type="email"
                value={contactEmail}
                onChange={(event) => onContactEmailChange?.(event.target.value)}
              />
            </label>
            <label className="block">
              <span className="eyebrow mb-1 block">Phone (optional)</span>
              <input
                autoComplete="tel"
                className="desk-input w-full"
                maxLength={32}
                placeholder="+44 20 1234 5678"
                type="tel"
                value={contactPhone}
                onChange={(event) => onContactPhoneChange?.(event.target.value)}
              />
            </label>
          </div>
        ) : null}
        <label
          aria-hidden="true"
          className="absolute left-[-10000px] top-auto h-px w-px overflow-hidden"
        >
          Website
          <input
            autoComplete="off"
            name="website"
            tabIndex={-1}
            value={website}
            onChange={(event) => onWebsiteChange?.(event.target.value)}
          />
        </label>
        <label className="block">
          <span className="eyebrow mb-1 block">
            Request purpose
          </span>
          <textarea
            className="desk-input min-h-24 w-full resize-y"
            placeholder="What do you need these items for?"
            value={requestedFor}
            onChange={(event) => onRequestedForChange(event.target.value)}
          />
        </label>
        <button
          className="desk-button-primary w-full disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!canSubmit}
          type="button"
          onClick={onSubmit}
        >
          {submitPending ? "Submitting..." : "Submit request"}
        </button>
        {submitError ? <Notice tone="danger" text={submitError} /> : null}
        {submitted ? (
          <div className="rounded-xl border border-success bg-success px-3 py-2 text-on-success dark:bg-success/15 dark:text-success-ink">
            <h3 className="title-section text-on-success dark:text-success-ink">Request submitted</h3>
            {accountLess ? (
              <>
                <p className="mt-1 text-xs">
                  Save this reference — an account-less request has no sign-in to come back
                  to, and staff will ask for it.
                </p>
                {publicToken ? (
                  <p className="mt-2 break-all rounded-lg bg-surface px-2 py-1 font-mono text-xs text-ink">
                    {publicToken}
                  </p>
                ) : null}
              </>
            ) : (
              <p className="mt-1 text-xs">
                Check this page with your email to follow the request.
              </p>
            )}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function Notice({ text, tone }: { text: string; tone: "danger" | "success" }) {
  const colors =
    tone === "success"
      ? "border-success bg-success text-on-success"
      : "border-danger/40 bg-danger/10 text-danger";
  return <p className={`rounded-lg border px-3 py-2 text-sm ${colors}`}>{text}</p>;
}
