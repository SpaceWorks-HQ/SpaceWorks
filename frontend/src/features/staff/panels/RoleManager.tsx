import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "../../../components/ui";
import { deleteRole, type Capability, type StaffRole } from "./rolesApi";
import { RoleEditor } from "./RoleEditor";
import { useStaffGet } from "./shared";

export function RoleManager({ msId, actorActions, isSuperadmin, onRolesChanged }: {
  msId: number;
  actorActions: readonly string[];
  isSuperadmin: boolean;
  onRolesChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const roles = useStaffGet<StaffRole[]>(["staff", "roles", msId], `/admin/makerspaces/${msId}/roles`);
  const capabilities = useStaffGet<Capability[]>(["staff", "capabilities", msId], `/admin/makerspaces/${msId}/roles/capabilities`);
  const [editing, setEditing] = useState<StaffRole | null | undefined>();
  const [deleteError, setDeleteError] = useState("");
  const labels = new Map((capabilities.data ?? []).map((item) => [item.value, item.label]));
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["staff", "roles", msId] });
    onRolesChanged();
  };
  const remove = useMutation({
    mutationFn: (role: StaffRole) => deleteRole(msId, role.id),
    onSuccess: refresh,
    onError: (error) => setDeleteError(error instanceof Error ? error.message : "Unable to delete role"),
  });

  return (
    <details className="rounded-md border border-line bg-bg">
      <summary className="cursor-pointer px-3 py-2 font-semibold text-ink">Roles</summary>
      <div className="grid gap-3 border-t border-line p-3">
        <div className="flex justify-end">
          <button className="desk-button-primary" type="button" onClick={() => { setDeleteError(""); setEditing(null); }}>
            New role
          </button>
        </div>
        {roles.error ? <p className="text-sm text-danger">{roles.error.message}</p> : null}
        {deleteError ? <p className="text-sm text-danger">{deleteError}</p> : null}
        {roles.isLoading ? <p className="text-sm text-muted">Loading roles...</p> : null}
        {!roles.isLoading && !roles.data?.length ? <EmptyState title="No roles" description="Create a role to assign staff." /> : null}
        <div className="grid gap-2">
          {roles.data?.map((role) => (
            <div key={role.id} className="flex flex-wrap items-center gap-2 rounded-md border border-line p-3 text-sm">
              <span className="font-semibold text-ink">{role.name}</span>
              <span className="rounded bg-surface px-2 py-0.5 text-xs text-muted">{role.is_default ? "Default" : "Custom"}</span>
              {role.is_protected ? <span className="rounded bg-surface px-2 py-0.5 text-xs text-muted">Protected</span> : null}
              <span className="text-muted">{role.member_count} members</span>
              <span className="min-w-48 flex-1 text-xs text-muted">{role.granted_actions.map((action) => labels.get(action) ?? action).join(", ") || "No capabilities"}</span>
              <button className="desk-button-ghost" type="button" onClick={() => { setDeleteError(""); setEditing(role); }}>Edit</button>
              <button className="desk-button-danger" type="button" disabled={role.is_protected || role.member_count > 0 || remove.isPending} onClick={() => { if (window.confirm(`Delete ${role.name}?`)) remove.mutate(role); }}>Delete</button>
            </div>
          ))}
        </div>
      </div>
      {editing !== undefined ? <RoleEditor msId={msId} role={editing} capabilities={capabilities.data ?? []} actorActions={actorActions} isSuperadmin={isSuperadmin} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); refresh(); }} /> : null}
    </details>
  );
}
