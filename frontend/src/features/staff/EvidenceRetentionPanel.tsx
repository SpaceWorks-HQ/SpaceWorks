import { useEffect, useState, type FormEvent } from "react";

import { EmptyState, Skeleton } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import {
  useEvidenceRetentionPolicy,
  useEvidenceRetentionPreview,
  useUpdateEvidenceRetention,
} from "./evidenceRetentionApi";


const bytes = (value: number) => new Intl.NumberFormat(undefined, {
  style: "unit",
  unit: "megabyte",
  maximumFractionDigits: 1,
}).format(value / 1_048_576);

const errorText = (error: unknown) =>
  error instanceof StructuredApiError
    ? error.detail ?? error.message
    : "Unable to load evidence retention settings.";

export function EvidenceRetentionPanel({ makerspaceId }: { makerspaceId: number }) {
  const policy = useEvidenceRetentionPolicy(makerspaceId);
  const update = useUpdateEvidenceRetention(makerspaceId);
  const effectiveDays = policy.data?.effective_days ?? 0;
  const preview = useEvidenceRetentionPreview(
    makerspaceId,
    effectiveDays,
    Boolean(policy.data),
  );
  const [days, setDays] = useState("");

  useEffect(() => {
    if (policy.data) setDays(String(policy.data.effective_days));
  }, [policy.data?.effective_days]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    update.mutate(Number(days));
  };

  if (policy.isLoading) return <Skeleton className="mb-5 h-40 w-full" />;
  if (policy.error) return (
    <EmptyState
      title="Unable to load evidence retention"
      description={errorText(policy.error)}
      action={<button className="desk-button" type="button" onClick={() => policy.refetch()}>Retry</button>}
    />
  );
  if (!policy.data) return null;

  return (
    <section className="mb-5 rounded-xl border border-line bg-bg p-4" aria-labelledby="evidence-retention-title">
      <h3 id="evidence-retention-title" className="title-section">Evidence photo retention</h3>
      <p className="mt-1 text-sm text-muted">
        Photo metadata and audit history remain immutable. Stored image bytes expire after the effective window.
      </p>
      <p className="mt-2 text-sm font-semibold text-warning" role="note">
        Expiry is irreversible in live storage; older backups may still contain historical photos.
      </p>
      <form className="mt-3 flex flex-wrap items-end gap-3" onSubmit={submit}>
        <label className="grid gap-1 text-sm font-semibold text-ink">
          Retention days
          <input
            className="desk-input w-40"
            type="number"
            min="30"
            max="3650"
            value={days}
            onChange={(event) => setDays(event.target.value)}
            required
          />
        </label>
        <button className="desk-button-primary" type="submit" disabled={update.isPending}>Save override</button>
        <button
          className="desk-button"
          type="button"
          disabled={update.isPending || policy.data.override_days === null}
          onClick={() => update.mutate(null)}
        >
          Use platform default
        </button>
      </form>
      <p className="mt-2 text-xs text-muted">
        {policy.data.override_days === null
          ? `Inherited platform default: ${policy.data.platform_default_days} days.`
          : `Tenant override: ${policy.data.override_days} days (platform default ${policy.data.platform_default_days}).`}
        {` Automatic expiry is ${policy.data.object_expiry_enabled ? "enabled" : "disabled"}.`}
      </p>
      {update.error ? <p className="mt-2 text-sm text-danger" role="alert">{errorText(update.error)}</p> : null}
      <div className="mt-3 rounded-lg border border-line bg-surface p-3 text-sm">
        {preview.isLoading ? <span className="text-muted">Calculating preview…</span> : null}
        {preview.error ? <span className="text-danger">{errorText(preview.error)}</span> : null}
        {preview.data ? (
          <p>
            <span className="font-semibold">Preview:</span>{` ${preview.data.object_candidates} photo objects (${bytes(preview.data.candidate_bytes)}) are eligible as of ${new Date(preview.data.as_of).toLocaleString()}.`}
            {preview.data.has_more ? " The first sweep will continue in bounded batches." : ""}
          </p>
        ) : null}
      </div>
    </section>
  );
}
