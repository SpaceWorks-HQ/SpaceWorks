import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog } from "../../../components/ui";
import { staffRequest, type StaffAuthUser } from "../../../lib/api";
import { Panel, useStaffGet, type Makerspace } from "./shared";
import { RoleManager } from "./RoleManager";
import { UsersTable } from "./UsersTable";
import {
  AddStaffModal,
  CreateMakerspaceModal,
  ResetPasswordModal,
  RestrictUserModal,
  type MakerspaceForm,
  type ResetPasswordForm,
  type ResetPasswordResult,
  type RestrictForm,
  type StaffForm,
} from "./UsersModals";
import {
  assignRole,
  createMembership,
  type StaffMembershipRow,
  type StaffRole,
} from "./rolesApi";

const emptyStaffForm: StaffForm = {
  username: "",
  email: "",
  first_name: "",
  last_name: "",
  password: "",
  role_id: "",
  makerspace_id: "",
};
const emptyRestrictForm: RestrictForm = { status: "restricted", reason: "" };
const emptyMakerspaceForm: MakerspaceForm = {
  name: "",
  public_code: "",
  slug: "",
  location: "",
  superadmin_access_enabled: true,
};
const emptyResetPasswordForm: ResetPasswordForm = { password: "" };

export function Users({ makerspaces, isSuperadmin, currentUser, onAuthRefresh }: {
  makerspaces: Makerspace[];
  isSuperadmin: boolean;
  currentUser: StaffAuthUser;
  onAuthRefresh: () => void;
}) {
  const queryClient = useQueryClient();
  const [msId, setMsId] = useState<number>(makerspaces[0]?.id ?? 0);
  const [roleFilter, setRoleFilter] = useState("all");
  const [addOpen, setAddOpen] = useState(false);
  const [makerspaceOpen, setMakerspaceOpen] = useState(false);
  const [staffForm, setStaffForm] = useState<StaffForm>(emptyStaffForm);
  const [makerspaceForm, setMakerspaceForm] = useState<MakerspaceForm>(emptyMakerspaceForm);
  const [restrictTarget, setRestrictTarget] = useState<StaffMembershipRow | null>(null);
  const [restrictForm, setRestrictForm] = useState<RestrictForm>(emptyRestrictForm);
  const [restoreTarget, setRestoreTarget] = useState<StaffMembershipRow | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<StaffMembershipRow | null>(null);
  const [resetPasswordTarget, setResetPasswordTarget] = useState<StaffMembershipRow | null>(null);
  const [resetPasswordForm, setResetPasswordForm] = useState<ResetPasswordForm>(emptyResetPasswordForm);
  const [resetPasswordResult, setResetPasswordResult] = useState<ResetPasswordResult | null>(null);

  // makerspaces may arrive after first mount (async load); the useState initializer only runs
  // once, so reconcile msId to a valid makerspace whenever the list changes or msId is stale.
  useEffect(() => {
    if (makerspaces.length && !makerspaces.some((space) => space.id === msId)) {
      setMsId(makerspaces[0].id);
    }
  }, [makerspaces, msId]);

  const memberships = useStaffGet<StaffMembershipRow[]>(["staff", "memberships", msId], `/admin/makerspaces/${msId}/memberships`, msId > 0);
  const rolesList = useStaffGet<StaffRole[]>(["staff", "roles", msId], `/admin/makerspaces/${msId}/roles`, msId > 0);

  const makerspaceNames = useMemo(() => new Map(makerspaces.map((space) => [space.id, space.name])), [makerspaces]);
  const actorActions = useMemo(
    () => currentUser.makerspaces.find((item) => item.id === msId)?.actions ?? [],
    [currentUser, msId],
  );
  const canManageRoles = isSuperadmin || actorActions.includes("manage_makerspace");
  const assignableRoles = useMemo(() => {
    const all = rolesList.data ?? [];
    if (isSuperadmin) return all;
    const ceiling = new Set(actorActions.filter((action) => action !== "manage_makerspace"));
    return all.filter(
      (role) => !role.granted_actions.includes("manage_makerspace") && role.granted_actions.every((action) => ceiling.has(action)),
    );
  }, [rolesList.data, isSuperadmin, actorActions]);

  const roleFilterOptions = useMemo(() => {
    const names = new Set<string>();
    (memberships.data ?? []).forEach((row) => names.add(row.assigned_role?.name ?? row.role));
    return Array.from(names).sort();
  }, [memberships.data]);
  const rows = useMemo(() => {
    const data = memberships.data ?? [];
    return roleFilter === "all" ? data : data.filter((row) => (row.assigned_role?.name ?? row.role) === roleFilter);
  }, [memberships.data, roleFilter]);

  // A role edit / assignment / revoke can change the CURRENT actor's own effective actions,
  // so refetch /auth/me (onAuthRefresh) in addition to invalidating the makerspace-scoped lists.
  const afterStaffChange = () => {
    queryClient.invalidateQueries({ queryKey: ["staff", "memberships", msId] });
    queryClient.invalidateQueries({ queryKey: ["staff", "roles", msId] });
    onAuthRefresh();
  };

  const createStaff = useMutation({
    mutationFn: () => createMembership(msId, staffPayload(staffForm)),
    onSuccess: () => { setAddOpen(false); setStaffForm(emptyStaffForm); afterStaffChange(); },
  });
  const changeRole = useMutation({
    mutationFn: ({ membership, roleId }: { membership: StaffMembershipRow; roleId: number }) => assignRole(msId, membership.id, roleId),
    onSuccess: afterStaffChange,
  });
  const restrict = useMutation({
    mutationFn: () =>
      restrictTarget
        ? staffRequest(`/admin/users/${restrictTarget.user.id}/restrict`, {
            method: "POST",
            body: JSON.stringify({ status: restrictForm.status, reason: restrictForm.reason.trim() }),
          })
        : Promise.resolve(),
    onSuccess: () => { setRestrictTarget(null); setRestrictForm(emptyRestrictForm); afterStaffChange(); },
  });
  const restore = useMutation({
    mutationFn: (membership: StaffMembershipRow) => staffRequest(`/admin/users/${membership.user.id}/restore-access`, { method: "POST" }),
    onSuccess: () => { setRestoreTarget(null); afterStaffChange(); },
  });
  const revoke = useMutation({
    mutationFn: (membership: StaffMembershipRow) => staffRequest(`/admin/memberships/${membership.id}`, { method: "DELETE" }),
    onSuccess: () => { setRevokeTarget(null); afterStaffChange(); },
  });
  const resetPassword = useMutation({
    mutationFn: () => {
      if (!resetPasswordTarget) throw new Error("No user selected");
      const password = resetPasswordForm.password;
      return staffRequest<ResetPasswordResult>(`/admin/users/${resetPasswordTarget.user.id}/reset-password`, {
        method: "POST",
        body: JSON.stringify(password ? { password } : {}),
      });
    },
    onSuccess: (result) => setResetPasswordResult(result),
  });
  const createMakerspace = useMutation({
    mutationFn: () => staffRequest("/admin/makerspaces", { method: "POST", body: JSON.stringify(makerspacePayload(makerspaceForm)) }),
    onSuccess: () => {
      setMakerspaceOpen(false);
      setMakerspaceForm(emptyMakerspaceForm);
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
    },
  });

  const openAdd = () => { setStaffForm({ ...emptyStaffForm, makerspace_id: String(msId) }); setAddOpen(true); };
  const openRestrict = (membership: StaffMembershipRow) => { setRestrictTarget(membership); setRestrictForm(emptyRestrictForm); };
  const openResetPassword = (membership: StaffMembershipRow) => {
    resetPassword.reset();
    setResetPasswordTarget(membership);
    setResetPasswordForm(emptyResetPasswordForm);
    setResetPasswordResult(null);
  };
  const closeResetPassword = () => {
    resetPassword.reset();
    setResetPasswordTarget(null);
    setResetPasswordForm(emptyResetPasswordForm);
    setResetPasswordResult(null);
  };

  if (!makerspaces.length) {
    return <Panel title="Users"><p className="text-sm text-muted">No makerspaces available for this account.</p></Panel>;
  }

  const panelError = memberships.error?.message ?? rolesList.error?.message ?? restore.error?.message;

  return (
    <Panel title="Users">
      <div className="grid gap-4">
        <div className="flex flex-wrap items-center gap-3">
          {makerspaces.length > 1 ? (
            <label className="eyebrow">
              Makerspace{" "}
              <select className="desk-input" value={msId} onChange={(event) => { setMsId(Number(event.target.value)); setRoleFilter("all"); }}>
                {makerspaces.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
              </select>
            </label>
          ) : null}
          <label className="eyebrow">
            Role{" "}
            <select className="desk-input" value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
              <option value="all">All roles</option>
              {roleFilterOptions.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
          <div className="desk-actions ml-auto flex flex-wrap gap-2">
            <button className="desk-button-primary" type="button" onClick={openAdd} disabled={!assignableRoles.length}>Add staff</button>
            {isSuperadmin ? <button className="desk-button" type="button" onClick={() => setMakerspaceOpen(true)}>Create makerspace</button> : null}
          </div>
        </div>

        {panelError ? <p className="text-sm text-danger">{panelError}</p> : null}
        <UsersTable
          rows={rows}
          makerspaceNames={makerspaceNames}
          loading={memberships.isLoading}
          assignableRoles={assignableRoles}
          onRestrict={openRestrict}
          onRestore={setRestoreTarget}
          onResetPassword={openResetPassword}
          onRevoke={setRevokeTarget}
          onChangeRole={(membership, roleId) => changeRole.mutateAsync({ membership, roleId })}
        />
        {canManageRoles ? (
          <RoleManager msId={msId} actorActions={actorActions} isSuperadmin={isSuperadmin} onRolesChanged={afterStaffChange} />
        ) : null}
      </div>

      <AddStaffModal
        open={addOpen}
        form={staffForm}
        makerspaceName={makerspaceNames.get(msId) ?? ""}
        pending={createStaff.isPending}
        error={createStaff.error}
        roles={assignableRoles}
        onChange={setStaffForm}
        onClose={() => setAddOpen(false)}
        onSubmit={() => createStaff.mutate()}
      />
      <RestrictUserModal
        open={Boolean(restrictTarget)}
        userLabel={restrictTarget?.user.username ?? ""}
        form={restrictForm}
        pending={restrict.isPending}
        error={restrict.error}
        onChange={setRestrictForm}
        onClose={() => setRestrictTarget(null)}
        onSubmit={() => restrict.mutate()}
      />
      <CreateMakerspaceModal
        open={makerspaceOpen}
        form={makerspaceForm}
        pending={createMakerspace.isPending}
        error={createMakerspace.error}
        onChange={setMakerspaceForm}
        onClose={() => setMakerspaceOpen(false)}
        onSubmit={() => createMakerspace.mutate()}
      />
      <ResetPasswordModal
        open={Boolean(resetPasswordTarget)}
        userLabel={resetPasswordTarget?.user.username ?? ""}
        form={resetPasswordForm}
        pending={resetPassword.isPending}
        error={resetPassword.error}
        result={resetPasswordResult}
        onChange={setResetPasswordForm}
        onClose={closeResetPassword}
        onSubmit={() => resetPassword.mutate()}
      />
      <ConfirmDialog
        open={Boolean(restoreTarget)}
        title="Restore access"
        message={restoreTarget ? `Restore access for ${restoreTarget.user.username}?` : ""}
        confirmLabel="Restore"
        pending={restore.isPending}
        onCancel={() => setRestoreTarget(null)}
        onConfirm={() => { if (restoreTarget) restore.mutate(restoreTarget); }}
      />
      <ConfirmDialog
        open={Boolean(revokeTarget)}
        title="Revoke role"
        message={
          revokeTarget
            ? `Remove ${revokeTarget.user.username}'s "${revokeTarget.assigned_role?.name ?? revokeTarget.role.replace(/_/g, " ")}" role in ${makerspaceNames.get(revokeTarget.makerspace_id) ?? revokeTarget.makerspace_slug}? Their account is not deleted.`
            : ""
        }
        confirmLabel="Revoke"
        pending={revoke.isPending}
        onCancel={() => setRevokeTarget(null)}
        onConfirm={() => { if (revokeTarget) revoke.mutate(revokeTarget); }}
      />
    </Panel>
  );
}

function staffPayload(form: StaffForm) {
  return {
    username: form.username.trim(),
    email: form.email.trim(),
    first_name: form.first_name.trim(),
    last_name: form.last_name.trim(),
    password: form.password,
    role_id: Number(form.role_id),
  };
}

function makerspacePayload(form: MakerspaceForm) {
  return {
    name: form.name.trim(),
    public_code: form.public_code.trim(),
    slug: form.slug.trim(),
    location: form.location.trim(),
    superadmin_access_enabled: form.superadmin_access_enabled,
  };
}
