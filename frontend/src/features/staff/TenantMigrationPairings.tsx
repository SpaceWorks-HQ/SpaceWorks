import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createPairing,
  getDeploymentIdentity,
  tenantMigrationKeys,
  type DeploymentIdentity,
  type Pairing,
} from "./tenantMigrationApi";
import { ErrorText } from "./tenantMigrationUi";

export function TenantMigrationPairings({ pairings }: { pairings: Pairing[] }) {
  const client = useQueryClient();
  const [migrationId, setMigrationId] = useState("");
  const [sourceTenantId, setSourceTenantId] = useState("");
  const [archiveDigest, setArchiveDigest] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [targetText, setTargetText] = useState("");
  const [localError, setLocalError] = useState("");
  const identity = useQuery({
    queryKey: tenantMigrationKeys.deploymentIdentity,
    queryFn: getDeploymentIdentity,
  });
  const localPairingIdentity = identity.data ? pairingIdentity(identity.data) : null;
  const effectiveTarget = targetText || (localPairingIdentity ? JSON.stringify(localPairingIdentity, null, 2) : "");
  const create = useMutation({
    mutationFn: (payload: Parameters<typeof createPairing>[0]) => createPairing(payload),
    onSuccess: () => client.invalidateQueries({ queryKey: tenantMigrationKeys.pairings }),
  });

  const submit = () => {
    try {
      const source = JSON.parse(sourceText) as Record<string, unknown>;
      const target = JSON.parse(effectiveTarget) as Record<string, unknown>;
      setLocalError("");
      create.mutate({
        migration_id: migrationId.trim(),
        source_tenant_id: sourceTenantId.trim(),
        archive_digest: archiveDigest.trim(),
        source,
        target,
      });
    } catch {
      setLocalError("Source and target deployment identities must be valid JSON objects.");
    }
  };

  return (
    <section aria-labelledby="migration-pairing-title" className="rounded-md border border-line bg-bg p-4">
      <p className="eyebrow">Two-deployment protocol</p>
      <h3 className="title-section" id="migration-pairing-title">Pin source and target identities</h3>
      <p className="mt-2 text-sm text-ink">
        Compare fingerprints out of band before pinning. Create the same pairing on both deployments;
        a receipt from an identity outside this pinned pair is refused.
      </p>
      {identity.data ? (
        <div className="mt-3 rounded-md border border-accent/40 bg-accent/10 p-3 text-sm">
          <p className="font-semibold text-accent-ink">This deployment: {identity.data.deployment_id}</p>
          <p className="mt-1 break-all font-mono text-xs text-muted">Fingerprint: {identity.data.fingerprint}</p>
          <p className="mt-1 break-all font-mono text-xs text-muted">Age recipient: {identity.data.age_recipient}</p>
          <label className="mt-2 block text-sm font-semibold text-ink">
            This deployment identity JSON
            <textarea className="desk-input mt-1 min-h-32 w-full font-mono text-xs" readOnly value={JSON.stringify(localPairingIdentity, null, 2)} />
          </label>
          <button className="desk-button mt-2" type="button" onClick={() => setSourceText(JSON.stringify(localPairingIdentity, null, 2))}>Use this deployment as source</button>
        </div>
      ) : null}
      {identity.isLoading ? <p className="mt-3 text-sm text-muted">Loading this deployment identity…</p> : null}
      <ErrorText error={identity.error} />

      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <label className="text-sm text-ink">Migration/import job ID<input className="desk-input mt-1 w-full font-mono" value={migrationId} onChange={(event) => setMigrationId(event.target.value)} /></label>
        <label className="text-sm text-ink">Source tenant ID<input className="desk-input mt-1 w-full font-mono" value={sourceTenantId} onChange={(event) => setSourceTenantId(event.target.value)} /></label>
        <label className="text-sm text-ink">Archive digest<input className="desk-input mt-1 w-full font-mono" value={archiveDigest} onChange={(event) => setArchiveDigest(event.target.value)} /></label>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="text-sm text-ink">Source deployment identity JSON<textarea className="desk-input mt-1 min-h-40 w-full font-mono text-xs" value={sourceText} onChange={(event) => setSourceText(event.target.value)} /></label>
        <label className="text-sm text-ink">Target deployment identity JSON<textarea className="desk-input mt-1 min-h-40 w-full font-mono text-xs" value={effectiveTarget} onChange={(event) => setTargetText(event.target.value)} /></label>
      </div>
      <button className="desk-button-primary mt-3" type="button" disabled={!migrationId.trim() || !sourceTenantId.trim() || !archiveDigest.trim() || !sourceText.trim() || !effectiveTarget.trim() || create.isPending} onClick={submit}>
        {create.isPending ? "Pinning identities…" : "Pin this deployment pairing"}
      </button>
      {localError ? <p className="mt-2 text-sm text-danger" role="alert">{localError}</p> : null}
      <ErrorText error={create.error} field="source" />

      <div className="mt-4 grid gap-2">
        {pairings.length === 0 ? <p className="text-sm text-muted">No migration pairings are pinned on this deployment.</p> : null}
        {pairings.map((pairing) => (
          <article className="rounded-md border border-line bg-surface p-3 text-xs" key={pairing.id}>
            <p className="font-semibold text-ink">Pairing <span className="font-mono">{pairing.id}</span></p>
            <p className="mt-1 break-all text-muted">Migration {pairing.migration_id} · archive {pairing.archive_digest}</p>
            <p className="mt-1 break-all font-mono text-muted">{pairing.source_fingerprint} → {pairing.target_fingerprint}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function pairingIdentity(identity: DeploymentIdentity) {
  const { algorithm, deployment_id, public_key, fingerprint } = identity;
  return { algorithm, deployment_id, public_key, fingerprint };
}
