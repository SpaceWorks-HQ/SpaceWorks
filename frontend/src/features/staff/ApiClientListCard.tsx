import { useEffect, useMemo, useState } from "react";

import { ApiClientScopePicker } from "./ApiClientScopePicker";
import type { ApiClient, ApiClientScopeOption, ApiKeyRequest } from "./apiClientsApi";

type Props = {
  canManageMakerspace: boolean;
  clients: ApiClient[] | undefined;
  clientsLoading: boolean;
  clientsError: Error | null;
  requests: ApiKeyRequest[] | undefined;
  deletePending: boolean;
  deleteError: Error | null;
  rotatePending: boolean;
  rotateError: Error | null;
  scopeOptions: ApiClientScopeOption[];
  scopesLoading: boolean;
  scopesError: Error | null;
  scopeUpdatePending: boolean;
  scopeUpdateError: Error | null;
  onDelete: (clientId: number) => void;
  onRotate: (clientId: number) => void;
  onScopesUpdate: (clientId: number, scopes: string[]) => void;
};

export function ApiClientListCard({
  canManageMakerspace,
  clients,
  clientsLoading,
  clientsError,
  requests,
  deletePending,
  deleteError,
  rotatePending,
  rotateError,
  scopeOptions,
  scopesLoading,
  scopesError,
  scopeUpdatePending,
  scopeUpdateError,
  onDelete,
  onRotate,
  onScopesUpdate,
}: Props) {
  if (canManageMakerspace) {
    return (
      <article className="rounded-md border border-line bg-surface p-3">
        <h3 className="font-semibold text-ink">Existing clients</h3>
        {clientsLoading ? <p className="mt-3 text-sm text-muted">Loading clients...</p> : null}
        <div className="mt-3 space-y-2">
          {clients?.map((client) => (
            <ApiClientRow
              key={client.id}
              client={client}
              scopeOptions={scopeOptions}
              scopesLoading={scopesLoading}
              updatePending={scopeUpdatePending}
              deletePending={deletePending}
              rotatePending={rotatePending}
              onDelete={onDelete}
              onRotate={onRotate}
              onScopesUpdate={onScopesUpdate}
            />
          ))}
        </div>
        {!clientsLoading && clients?.length === 0 ? (
          <p className="mt-3 text-sm text-muted">No API clients yet.</p>
        ) : null}
        {clientsError ? <p className="mt-3 text-sm text-danger">{clientsError.message}</p> : null}
        {scopesError ? <p className="mt-3 text-sm text-danger">{scopesError.message}</p> : null}
        {scopeUpdateError ? <p className="mt-3 text-sm text-danger">{scopeUpdateError.message}</p> : null}
        {deleteError ? <p className="mt-3 text-sm text-danger">{deleteError.message}</p> : null}
        {rotateError ? <p className="mt-3 text-sm text-danger">{rotateError.message}</p> : null}
      </article>
    );
  }

  return (
    <>
      <article className="rounded-md border border-line bg-surface p-3">
        <h3 className="font-semibold text-ink">Your requests</h3>
        <div className="mt-3 space-y-2">
          {requests?.map((request) => (
            <div key={request.id} className="rounded-md border border-line bg-bg p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-semibold text-ink">{request.label}</p>
                  <p className="mt-1 text-xs text-muted">{formatDate(request.created_at)}</p>
                </div>
                <span className="rounded-md border border-line bg-surface px-2 py-1 text-xs font-semibold text-muted">
                  {request.status}
                </span>
              </div>
              {request.resolution_note ? (
                <p className="mt-2 text-sm text-muted">{request.resolution_note}</p>
              ) : null}
            </div>
          ))}
        </div>
      </article>
      {requests?.length === 0 ? (
        <p className="rounded-md border border-line bg-surface p-3 text-sm text-muted">
          No API access requests yet.
        </p>
      ) : null}
    </>
  );
}

function ApiClientRow({ client, scopeOptions, scopesLoading, updatePending, deletePending, rotatePending, onDelete, onRotate, onScopesUpdate }: {
  client: ApiClient;
  scopeOptions: ApiClientScopeOption[];
  scopesLoading: boolean;
  updatePending: boolean;
  deletePending: boolean;
  rotatePending: boolean;
  onDelete: (clientId: number) => void;
  onRotate: (clientId: number) => void;
  onScopesUpdate: (clientId: number, scopes: string[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>(client.scopes);
  useEffect(() => setSelected(client.scopes), [client.scopes]);
  const grantable = useMemo(
    () => selected.filter((scope) => scopeOptions.some((option) => option.value === scope && option.grantable)),
    [scopeOptions, selected],
  );
  const hasLegacy = client.scopes.includes("legacy:v1");
  const changed = grantable.join("\0") !== client.scopes.join("\0");

  return (
    <div className="rounded-md border border-line bg-bg p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><p className="font-semibold text-ink">{client.label}</p><p className="mt-1 break-all font-mono text-xs text-muted">{client.client_id}</p></div>
        <span className={`rounded-md px-2 py-1 text-xs font-semibold ${client.is_active ? "bg-success/15 text-success-ink" : "bg-warn/15 text-warn-ink"}`}>{client.is_active ? "Active" : "Inactive"}</span>
      </div>
      <p className="mt-2 break-all text-xs text-muted">{client.allowed_origins.length ? `Origins: ${client.allowed_origins.join(", ")}` : "No browser origins configured."}</p>
      <p className="mt-2 text-xs text-muted">Scopes: {client.scopes.join(", ")}</p>
      {hasLegacy ? <p className="mt-2 rounded-md border border-warn/40 bg-warn/10 p-2 text-xs text-warn-ink">Legacy v1 access preserves the frozen cutover capability. Select explicit replacement scopes and save; viewing this client never changes it.</p> : null}
      {scopesLoading ? <p className="mt-2 text-xs text-muted">Loading scope choices...</p> : null}
      {!scopesLoading && scopeOptions.length ? <div className="mt-2"><ApiClientScopePicker options={scopeOptions} selected={selected} onChange={setSelected} disabled={updatePending} /></div> : null}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted">{formatDate(client.created_at)} · {client.last_seen_at ? `last used ${formatDate(client.last_seen_at)}` : "never used"}</p>
        <div className="desk-actions flex flex-wrap gap-2">
          <button className="desk-button-primary" type="button" disabled={updatePending || !grantable.length || !changed} onClick={() => onScopesUpdate(client.id, grantable)}>Save scopes</button>
          <button className="desk-button" type="button" disabled={rotatePending} onClick={() => onRotate(client.id)}>Rotate secret</button>
          <button className="desk-button" type="button" disabled={deletePending} onClick={() => onDelete(client.id)}>Delete</button>
        </div>
      </div>
    </div>
  );
}

function formatDate(value: string) {
  return new Date(value).toLocaleString();
}
