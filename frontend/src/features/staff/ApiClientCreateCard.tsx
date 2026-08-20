import { ApiClientScopePicker } from "./ApiClientScopePicker";
import type { ApiClientCreateResponse, ApiClientScopeOption } from "./apiClientsApi";
import { splitOrigins } from "./apiClientsApi";

type Props = {
  canManageMakerspace: boolean;
  label: string;
  reason: string;
  origins: string;
  submitted: boolean;
  oneTimeSecret: ApiClientCreateResponse | null;
  isPending: boolean;
  error: Error | null;
  scopeOptions: ApiClientScopeOption[];
  scopes: string[];
  scopesLoading: boolean;
  scopesError: Error | null;
  onLabelChange: (value: string) => void;
  onReasonChange: (value: string) => void;
  onOriginsChange: (value: string) => void;
  onScopesChange: (value: string[]) => void;
  onSubmit: () => void;
  onDismissSecret: () => void;
};

export function ApiClientCreateCard({
  canManageMakerspace,
  label,
  reason,
  origins,
  submitted,
  oneTimeSecret,
  isPending,
  error,
  scopeOptions,
  scopes,
  scopesLoading,
  scopesError,
  onLabelChange,
  onReasonChange,
  onOriginsChange,
  onScopesChange,
  onSubmit,
  onDismissSecret,
}: Props) {
  if (canManageMakerspace) {
    return (
      <article className="rounded-md border border-line bg-surface p-3">
        <h3 className="font-semibold text-ink">API clients</h3>
        <div className="mt-3 grid gap-2">
          <input
            className="desk-input w-full"
            placeholder="Client label"
            value={label}
            onChange={(event) => onLabelChange(event.target.value)}
          />
          <textarea
            className="desk-input min-h-24 w-full"
            placeholder="Allowed browser origins, one per line. Example: https://lab.example.com"
            value={origins}
            onChange={(event) => onOriginsChange(event.target.value)}
          />
          <div className="grid gap-2">
            <span className="eyebrow">Scopes</span>
            <p className="text-xs text-muted">Choose the exact public API access this client needs.</p>
            {scopesLoading ? <p className="text-sm text-muted">Loading scope choices...</p> : null}
            {!scopesLoading && scopeOptions.length ? (
              <ApiClientScopePicker
                options={scopeOptions}
                selected={scopes}
                onChange={onScopesChange}
                disabled={isPending}
              />
            ) : null}
            {scopesError ? <p className="text-sm text-danger">{scopesError.message}</p> : null}
          </div>
        </div>
        <button
          className="desk-button-primary mt-3 w-full"
          disabled={!label.trim() || !splitOrigins(origins).length || !scopes.length || scopesLoading || !!scopesError || isPending}
          onClick={onSubmit}
        >
          {isPending ? "Creating..." : "Create API client"}
        </button>
        {error ? <p className="mt-2 text-sm text-danger">{error.message}</p> : null}
        {oneTimeSecret ? (
          <div className="mt-3 rounded-md border border-accent/40 bg-accent/10 p-3">
            <p className="text-sm font-semibold text-ink">Copy this secret now &mdash; it will not be shown again.</p>
            <p className="mt-2 break-all rounded-md border border-line bg-bg p-2 font-mono text-xs text-ink">
              {oneTimeSecret.client_secret}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                className="desk-button"
                type="button"
                onClick={() => void navigator.clipboard.writeText(oneTimeSecret.client_secret)}
              >
                Copy
              </button>
              <button className="desk-button-primary" type="button" onClick={onDismissSecret}>
                Done
              </button>
            </div>
          </div>
        ) : null}
      </article>
    );
  }

  return (
    <article className="rounded-md border border-line bg-surface p-3">
      <h3 className="font-semibold text-ink">Request API access</h3>
      <div className="mt-3 grid gap-2">
        <input
          className="desk-input w-full"
          placeholder="Request label"
          value={label}
          onChange={(event) => onLabelChange(event.target.value)}
        />
        <textarea
          className="desk-input min-h-24 w-full"
          placeholder="Reason for API access"
          value={reason}
          onChange={(event) => onReasonChange(event.target.value)}
        />
        <textarea
          className="desk-input min-h-24 w-full"
          placeholder="Allowed browser origins, one per line. Example: https://lab.example.com"
          value={origins}
          onChange={(event) => onOriginsChange(event.target.value)}
        />
      </div>
      <button
        className="desk-button-primary mt-3 w-full"
        disabled={!label.trim() || !reason.trim() || !splitOrigins(origins).length || isPending}
        onClick={onSubmit}
      >
        {isPending ? "Submitting..." : "Submit API access request"}
      </button>
      {submitted ? (
        <p className="mt-2 text-sm text-muted">
          Request submitted. A superadmin will review and share the key with you securely.
        </p>
      ) : null}
      {error ? <p className="mt-2 text-sm text-danger">{error.message}</p> : null}
    </article>
  );
}
