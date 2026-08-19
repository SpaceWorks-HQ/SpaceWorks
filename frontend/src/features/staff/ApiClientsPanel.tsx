import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { ApiClientsAccessSummary } from "./ApiClientsAccessSummary";
import { ApiClientsTelegramSettings } from "./ApiClientsTelegramSettings";
import { Panel, type Makerspace, useStaffGet } from "./StaffPanels";

type ApiKeyRequest = {
  id: number;
  label: string;
  status: "pending" | "approved" | "rejected";
  resolution_note: string;
  created_at: string;
};
type ApiClient = {
  id: number;
  label: string;
  client_id: string;
  last_seen_at: string | null;
  allowed_origins: string[];
  is_active: boolean;
  created_at: string;
};
type ApiClientCreateResponse = ApiClient & {
  client_secret: string;
};
type ApiSettings = {
  public_code: string;
  cors_allowed_origins: string[];
};

export function ApiClientsPanel({
  makerspace,
  isSuperadmin,
  canManageMakerspace,
}: {
  makerspace: Makerspace;
  isSuperadmin: boolean;
  canManageMakerspace: boolean;
}) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const [reason, setReason] = useState("");
  const [origins, setOrigins] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [oneTimeSecret, setOneTimeSecret] = useState<ApiClientCreateResponse | null>(null);
  const requests = useStaffGet<{ results: ApiKeyRequest[] }>(
    ["api-key-requests", makerspace.id],
    `/admin/api-key-requests?makerspace=${makerspace.id}`,
    !canManageMakerspace,
  );
  const apiClients = useStaffGet<{ results: ApiClient[] }>(
    ["api-clients", makerspace.id],
    `/admin/makerspace/${makerspace.id}/api-clients`,
    canManageMakerspace,
  );
  const settings = useStaffGet<ApiSettings>(
    ["api-settings", makerspace.id],
    `/admin/makerspace/${makerspace.id}/api-settings`,
    isSuperadmin,
  );

  const requestKey = useMutation({
    mutationFn: () =>
      staffRequest<ApiKeyRequest>("/admin/api-key-requests", {
        method: "POST",
        body: JSON.stringify({
          makerspace: makerspace.id,
          label,
          reason,
          allowed_origins: splitOrigins(origins),
        }),
      }),
    onSuccess: () => {
      setLabel("");
      setReason("");
      setOrigins("");
      setSubmitted(true);
      queryClient.invalidateQueries({ queryKey: ["api-key-requests", makerspace.id] });
    },
  });
  const createClient = useMutation({
    mutationFn: () =>
      staffRequest<ApiClientCreateResponse>(`/admin/makerspace/${makerspace.id}/api-clients`, {
        method: "POST",
        body: JSON.stringify({
          label,
          allowed_origins: splitOrigins(origins),
        }),
      }),
    onSuccess: (created) => {
      setLabel("");
      setOrigins("");
      setOneTimeSecret(created);
      queryClient.invalidateQueries({ queryKey: ["api-clients", makerspace.id] });
    },
  });
  const deleteClient = useMutation({
    mutationFn: (clientId: number) =>
      staffRequest<void>(`/admin/api-clients/${clientId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-clients", makerspace.id] });
    },
  });
  const rotateClient = useMutation({
    mutationFn: (clientId: number) =>
      staffRequest<ApiClientCreateResponse>(`/admin/api-clients/${clientId}/rotate-secret`, {
        method: "POST",
      }),
    onSuccess: (rotated) => {
      setOneTimeSecret(rotated);
      queryClient.invalidateQueries({ queryKey: ["api-clients", makerspace.id] });
    },
  });

  return (
    <Panel title="API access">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          {canManageMakerspace ? (
            <article className="rounded-md border border-line bg-surface p-3">
              <h3 className="font-semibold text-ink">API clients</h3>
              <div className="mt-3 grid gap-2">
                <input
                  className="desk-input w-full"
                  placeholder="Client label"
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                />
                <textarea
                  className="desk-input min-h-24 w-full"
                  placeholder="Allowed browser origins, one per line. Example: https://lab.example.com"
                  value={origins}
                  onChange={(event) => setOrigins(event.target.value)}
                />
              </div>
              <button
                className="desk-button-primary mt-3 w-full"
                disabled={!label.trim() || !splitOrigins(origins).length || createClient.isPending}
                onClick={() => createClient.mutate()}
              >
                {createClient.isPending ? "Creating..." : "Create API client"}
              </button>
              {createClient.error ? <p className="mt-2 text-sm text-danger">{createClient.error.message}</p> : null}
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
                    <button className="desk-button-primary" type="button" onClick={() => setOneTimeSecret(null)}>
                      Done
                    </button>
                  </div>
                </div>
              ) : null}
            </article>
          ) : (
            <article className="rounded-md border border-line bg-surface p-3">
              <h3 className="font-semibold text-ink">Request API access</h3>
              <div className="mt-3 grid gap-2">
                <input
                  className="desk-input w-full"
                  placeholder="Request label"
                  value={label}
                  onChange={(event) => {
                    setLabel(event.target.value);
                    setSubmitted(false);
                  }}
                />
                <textarea
                  className="desk-input min-h-24 w-full"
                  placeholder="Reason for API access"
                  value={reason}
                  onChange={(event) => {
                    setReason(event.target.value);
                    setSubmitted(false);
                  }}
                />
                <textarea
                  className="desk-input min-h-24 w-full"
                  placeholder="Allowed browser origins, one per line. Example: https://lab.example.com"
                  value={origins}
                  onChange={(event) => {
                    setOrigins(event.target.value);
                    setSubmitted(false);
                  }}
                />
              </div>
              <button
                className="desk-button-primary mt-3 w-full"
                disabled={!label.trim() || !reason.trim() || !splitOrigins(origins).length || requestKey.isPending}
                onClick={() => requestKey.mutate()}
              >
                {requestKey.isPending ? "Submitting..." : "Submit API access request"}
              </button>
              {submitted ? (
                <p className="mt-2 text-sm text-muted">
                  Request submitted. A superadmin will review and share the key with you securely.
                </p>
              ) : null}
              {requestKey.error ? <p className="mt-2 text-sm text-danger">{requestKey.error.message}</p> : null}
            </article>
          )}

          {isSuperadmin ? <ApiClientsTelegramSettings makerspace={makerspace} /> : null}
        </div>

        <div className="space-y-3">
          <ApiClientsAccessSummary makerspace={makerspace} isSuperadmin={isSuperadmin} settings={settings.data} />

          {canManageMakerspace ? (
            <article className="rounded-md border border-line bg-surface p-3">
              <h3 className="font-semibold text-ink">Existing clients</h3>
              {apiClients.isLoading ? <p className="mt-3 text-sm text-muted">Loading clients...</p> : null}
              <div className="mt-3 space-y-2">
                {apiClients.data?.results?.map((client) => (
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
                          disabled={rotateClient.isPending}
                          onClick={() => rotateClient.mutate(client.id)}
                        >
                          Rotate secret
                        </button>
                        <button
                          className="desk-button"
                          type="button"
                          disabled={deleteClient.isPending}
                          onClick={() => deleteClient.mutate(client.id)}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              {!apiClients.isLoading && apiClients.data?.results?.length === 0 ? (
                <p className="mt-3 text-sm text-muted">No API clients yet.</p>
              ) : null}
              {apiClients.error ? <p className="mt-3 text-sm text-danger">{apiClients.error.message}</p> : null}
              {deleteClient.error ? <p className="mt-3 text-sm text-danger">{deleteClient.error.message}</p> : null}
              {rotateClient.error ? <p className="mt-3 text-sm text-danger">{rotateClient.error.message}</p> : null}
            </article>
          ) : (
            <>
              <article className="rounded-md border border-line bg-surface p-3">
                <h3 className="font-semibold text-ink">Your requests</h3>
                <div className="mt-3 space-y-2">
                  {requests.data?.results?.map((request) => (
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
              {requests.data?.results?.length === 0 ? (
                <p className="rounded-md border border-line bg-surface p-3 text-sm text-muted">
                  No API access requests yet.
                </p>
              ) : null}
            </>
          )}
        </div>
      </div>
    </Panel>
  );
}

function splitOrigins(value: string) {
  return value
    .split(/\r?\n|,/)
    .map((origin) => origin.trim())
    .filter(Boolean);
}

function formatDate(value: string) {
  return new Date(value).toLocaleString();
}
