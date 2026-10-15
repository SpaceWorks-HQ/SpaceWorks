import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";

type Settings = { request_access: "members" | "accounts" | "anyone"; anonymous_requests_enabled: boolean };

export function BorrowRequestAccessSettings({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const key = ["makerspace-settings", makerspaceId];
  const path = `/admin/makerspaces/${makerspaceId}`;
  const query = useQuery({ queryKey: key, queryFn: () => staffRequest<Settings>(path) });
  const save = useMutation({
    mutationFn: (mode: string) => staffRequest<Settings>(path, { method: "PATCH", body: JSON.stringify({ anonymous_requests_enabled: mode === "anyone" }) }),
    onSuccess: (data) => {
      client.setQueryData(key, data);
      for (const queryKey of [["staff", "makerspaces"], ["tenant-bootstrap"], ["runtime-tenant"]]) {
        void client.invalidateQueries({ queryKey });
      }
    },
  });
  const membersRequired = query.data?.request_access === "members";
  return <section className="grid gap-3 rounded-md border border-line p-4">
    <h3 className="title-section">Borrow request access</h3>
    <p className="text-sm text-muted">Membership requires active members. A superadmin can change that area in Modules. With Membership off, choose signed-in accounts or account-less requests; staff still review every request.</p>
    <label className="grid gap-1 text-sm">Who can submit borrow requests?
      <select className="desk-input" value={query.data?.request_access ?? "accounts"} disabled={!query.data || membersRequired || save.isPending} onChange={(event) => save.mutate(event.target.value)}>
        {membersRequired ? <option value="members">Active members only</option> : <><option value="accounts">Anyone with an account</option><option value="anyone">Anyone, no account</option></>}
      </select>
    </label>
    {query.error || save.error ? <p role="alert" className="text-danger">{(save.error ?? query.error)?.message}</p> : null}
  </section>;
}
