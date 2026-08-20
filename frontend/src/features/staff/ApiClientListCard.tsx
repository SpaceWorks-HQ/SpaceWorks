import type { ApiClient, ApiKeyRequest } from "./apiClientsApi";

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
  onDelete: (clientId: number) => void;
  onRotate: (clientId: number) => void;
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
  onDelete,
  onRotate,
}: Props) {
  if (canManageMakerspace) {
    return (
      <article className="rounded-md border border-line bg-surface p-3">
        <h3 className="font-semibold text-ink">Existing clients</h3>
        {clientsLoading ? <p className="mt-3 text-sm text-muted">Loading clients...</p> : null}
        <div className="mt-3 space-y-2">
          {clients?.map((client) => (
            <div key={client.id} className="rounded-md border border-line bg-bg p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-semibold text-ink">{client.label}</p>
                  <p className="mt-1 break-all font-mono text-xs text-muted">{client.client_id}</p>
                </div>
                <span className={`rounded-md px-2 py-1 text-xs font-semibold ${client.is_active ? "bg-success/15 text-success-ink" : "bg-warn/15 text-warn-ink"}`}>
                  {client.is_active ? "Active" : "Inactive"}
                </span>
              </div>
              {client.allowed_origins?.length ? (
                <p className="mt-2 break-all text-xs text-muted">Origins: {client.allowed_origins.join(", ")}</p>
              ) : (
                <p className="mt-2 text-xs text-muted">No browser origins configured.</p>
              )}
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                {/* Last seen, not just created: deciding whether a client is stale is
                    the whole reason the usage telemetry exists, and an operator reading
                    only a creation date cannot make that call. */}
                <p className="text-xs text-muted">
                  {formatDate(client.created_at)}
                  {" · "}
                  {client.last_seen_at
                    ? `last used ${formatDate(client.last_seen_at)}`
                    : "never used"}
                </p>
                <div className="desk-actions flex flex-wrap gap-2">
                  <button
                    className="desk-button"
                    type="button"
                    disabled={rotatePending}
                    onClick={() => onRotate(client.id)}
                  >
                    Rotate secret
                  </button>
                  <button
                    className="desk-button"
                    type="button"
                    disabled={deletePending}
                    onClick={() => onDelete(client.id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
        {!clientsLoading && clients?.length === 0 ? (
          <p className="mt-3 text-sm text-muted">No API clients yet.</p>
        ) : null}
        {clientsError ? <p className="mt-3 text-sm text-danger">{clientsError.message}</p> : null}
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

function formatDate(value: string) {
  return new Date(value).toLocaleString();
}
