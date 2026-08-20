import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiClientCreateCard } from "./ApiClientCreateCard";
import { ApiClientListCard } from "./ApiClientListCard";
import {
  apiClientsQueryKey,
  apiClientScopesQueryKey,
  apiKeyRequestsQueryKey,
  apiSettingsQueryKey,
  createApiClient,
  deleteApiClient,
  requestApiKey,
  rotateApiClient,
  splitOrigins,
  type ApiClient,
  type ApiClientCreateResponse,
  type ApiKeyRequest,
  type ApiSettings,
  type ApiClientScopeOption,
  updateApiClientScopes,
} from "./apiClientsApi";
import { ApiClientsAccessSummary } from "./ApiClientsAccessSummary";
import { ApiClientsTelegramSettings } from "./ApiClientsTelegramSettings";
import { Panel, type Makerspace, useStaffGet } from "./StaffPanels";

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
  const [scopes, setScopes] = useState<string[]>([]);
  const [submitted, setSubmitted] = useState(false);
  const [oneTimeSecret, setOneTimeSecret] = useState<ApiClientCreateResponse | null>(null);
  const requests = useStaffGet<{ results: ApiKeyRequest[] }>(
    apiKeyRequestsQueryKey(makerspace.id),
    `/admin/api-key-requests?makerspace=${makerspace.id}`,
    !canManageMakerspace,
  );
  const apiClients = useStaffGet<{ results: ApiClient[] }>(
    apiClientsQueryKey(makerspace.id),
    `/admin/makerspace/${makerspace.id}/api-clients`,
    canManageMakerspace,
  );
  const scopeOptions = useStaffGet<ApiClientScopeOption[]>(
    apiClientScopesQueryKey(makerspace.id),
    `/admin/makerspace/${makerspace.id}/api-client-scopes`,
    canManageMakerspace,
  );
  const settings = useStaffGet<ApiSettings>(
    apiSettingsQueryKey(makerspace.id),
    `/admin/makerspace/${makerspace.id}/api-settings`,
    isSuperadmin,
  );

  const requestKey = useMutation({
    mutationFn: () => requestApiKey(makerspace.id, label, reason, splitOrigins(origins)),
    onSuccess: () => {
      setLabel("");
      setReason("");
      setOrigins("");
      setSubmitted(true);
      queryClient.invalidateQueries({ queryKey: apiKeyRequestsQueryKey(makerspace.id) });
    },
  });
  const createClient = useMutation({
    mutationFn: () => createApiClient(makerspace.id, label, splitOrigins(origins), scopes),
    onSuccess: (created) => {
      setLabel("");
      setOrigins("");
      setScopes([]);
      setOneTimeSecret(created);
      queryClient.invalidateQueries({ queryKey: apiClientsQueryKey(makerspace.id) });
    },
  });
  const deleteClient = useMutation({
    mutationFn: deleteApiClient,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: apiClientsQueryKey(makerspace.id) });
    },
  });
  const rotateClient = useMutation({
    mutationFn: rotateApiClient,
    onSuccess: (rotated) => {
      setOneTimeSecret(rotated);
      queryClient.invalidateQueries({ queryKey: apiClientsQueryKey(makerspace.id) });
    },
  });
  const updateScopes = useMutation({
    mutationFn: ({ clientId, nextScopes }: { clientId: number; nextScopes: string[] }) => (
      updateApiClientScopes(clientId, nextScopes)
    ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: apiClientsQueryKey(makerspace.id) });
    },
  });

  const handleLabelChange = (value: string) => {
    setLabel(value);
    if (!canManageMakerspace) setSubmitted(false);
  };
  const handleReasonChange = (value: string) => {
    setReason(value);
    setSubmitted(false);
  };
  const handleOriginsChange = (value: string) => {
    setOrigins(value);
    if (!canManageMakerspace) setSubmitted(false);
  };

  return (
    <Panel title="API access">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          <ApiClientCreateCard
            canManageMakerspace={canManageMakerspace}
            label={label}
            reason={reason}
            origins={origins}
            submitted={submitted}
            oneTimeSecret={oneTimeSecret}
            isPending={canManageMakerspace ? createClient.isPending : requestKey.isPending}
            error={canManageMakerspace ? createClient.error : requestKey.error}
            scopeOptions={scopeOptions.data ?? []}
            scopes={scopes}
            scopesLoading={scopeOptions.isLoading}
            scopesError={scopeOptions.error}
            onLabelChange={handleLabelChange}
            onReasonChange={handleReasonChange}
            onOriginsChange={handleOriginsChange}
            onScopesChange={setScopes}
            onSubmit={() => canManageMakerspace ? createClient.mutate() : requestKey.mutate()}
            onDismissSecret={() => setOneTimeSecret(null)}
          />

          {isSuperadmin ? <ApiClientsTelegramSettings makerspace={makerspace} /> : null}
        </div>

        <div className="space-y-3">
          <ApiClientsAccessSummary makerspace={makerspace} isSuperadmin={isSuperadmin} settings={settings.data} />

          <ApiClientListCard
            canManageMakerspace={canManageMakerspace}
            clients={apiClients.data?.results}
            clientsLoading={apiClients.isLoading}
            clientsError={apiClients.error}
            requests={requests.data?.results}
            deletePending={deleteClient.isPending}
            deleteError={deleteClient.error}
            rotatePending={rotateClient.isPending}
            rotateError={rotateClient.error}
            scopeOptions={scopeOptions.data ?? []}
            scopesLoading={scopeOptions.isLoading}
            scopesError={scopeOptions.error}
            scopeUpdatePending={updateScopes.isPending}
            scopeUpdateError={updateScopes.error}
            onDelete={(clientId) => deleteClient.mutate(clientId)}
            onRotate={(clientId) => rotateClient.mutate(clientId)}
            onScopesUpdate={(clientId, nextScopes) => updateScopes.mutate({ clientId, nextScopes })}
          />
        </div>
      </div>
    </Panel>
  );
}
