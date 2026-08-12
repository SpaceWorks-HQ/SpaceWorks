import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Modal } from "../../../components/ui";
import { StructuredApiError } from "../../../lib/api";
import { createRole, updateRole, type Capability, type StaffRole } from "./rolesApi";
import { RoleMachineScopeEditor } from "./RoleMachineScopeEditor";

const presets: { label: string; actions: string[] }[] = [
  { label: "Space Manager", actions: ["view_inventory", "edit_inventory", "manage_qr", "accept_request", "reject_request", "assign_box", "issue_request", "issue_direct_loan", "return_request", "upload_evidence", "manage_printing", "manage_machines", "view_audit", "manage_events", "manage_bookings", "manage_makerspace"] },
  { label: "Inventory Manager", actions: ["view_inventory", "edit_inventory", "manage_qr", "accept_request", "reject_request", "assign_box", "issue_request", "issue_direct_loan", "return_request", "upload_evidence", "view_audit"] },
  { label: "Machine Manager", actions: ["manage_machines"] },
  { label: "Front Desk", actions: ["view_inventory", "assign_box", "issue_request", "issue_direct_loan", "return_request", "upload_evidence"] },
];

export function RoleEditor({ msId, role, capabilities, actorActions, isSuperadmin, onClose, onSaved }: {
  msId: number;
  role: StaffRole | null;
  capabilities: Capability[];
  actorActions: readonly string[];
  isSuperadmin: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const canManageRoles = isSuperadmin || actorActions.includes("manage_makerspace");
  const grouped = useMemo(() => {
    const groups = new Map<string, Capability[]>();
    capabilities.forEach((capability) => groups.set(capability.group, [...(groups.get(capability.group) ?? []), capability]));
    return groups;
  }, [capabilities]);

  useEffect(() => {
    setName(role?.name ?? "");
    setChecked(new Set(role?.granted_actions ?? []));
  }, [role?.id, role?.name, role?.granted_actions]);

  const save = useMutation({
    mutationFn: () => {
      const granted_actions = capabilities.filter((item) => item.grantable && checked.has(item.value)).map((item) => item.value);
      const body = { name: name.trim(), granted_actions };
      return role ? updateRole(msId, role.id, body) : createRole(msId, body);
    },
    onSuccess: onSaved,
  });
  const errorBody: Record<string, unknown> = save.error instanceof StructuredApiError ? save.error.body : {};
  const nameError = fieldError(errorBody.name);
  const actionsError = fieldError(errorBody.granted_actions);
  const disabled = save.isPending || !name.trim() || !canManageRoles;

  const applyPreset = (actions: string[]) => {
    setChecked(new Set(actions.filter((action) => capabilities.some((item) => item.value === action && item.grantable))));
  };
  const toggle = (value: string, enabled: boolean) => {
    if (!enabled) return;
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(value)) next.delete(value); else next.add(value);
      return next;
    });
  };

  return (
    <Modal open onClose={onClose} title={role ? `Edit ${role.name}` : "New role"} size="xl" footer={<div className="desk-actions flex justify-end gap-2"><button className="desk-button-ghost" type="button" disabled={save.isPending} onClick={onClose}>Cancel</button><button className="desk-button-primary" type="button" disabled={disabled} onClick={() => save.mutate()}>{save.isPending ? "Saving..." : "Save role"}</button></div>}>
      <div className="grid gap-4 text-sm">
        {role?.is_protected ? <p className="rounded-md border border-line bg-surface p-3 text-muted">Protected default — cannot be deleted; core capabilities are locked.</p> : null}
        {!role ? <div className="grid gap-2"><span className="eyebrow">Start from</span><div className="flex flex-wrap gap-2">{presets.map((preset) => <button className="desk-button-ghost" key={preset.label} type="button" onClick={() => applyPreset(preset.actions)}>{preset.label}</button>)}</div></div> : null}
        <label className="grid gap-1"><span className="eyebrow">Name</span><input className="desk-input w-full" value={name} onChange={(event) => setName(event.target.value)} /></label>
        {nameError ? <p className="text-sm text-danger">{nameError}</p> : null}
        {actionsError ? <p className="text-sm text-danger">{actionsError}</p> : null}
        {Array.from(grouped.entries()).map(([group, items]) => <section key={group} className="grid gap-2 rounded-md border border-line p-3"><h3 className="title-section">{group}</h3>{items.map((item) => <label key={item.value} className="flex items-start gap-3"><input className="mt-1 h-4 w-4 accent-accent" type="checkbox" checked={checked.has(item.value)} disabled={!item.grantable} onChange={() => toggle(item.value, item.grantable)} /><span className="grid gap-0.5"><span className="font-semibold text-ink">{item.label}</span><span className="text-xs text-muted">{item.description}</span>{!item.grantable ? <span className="text-xs text-danger">{item.lock_reason ?? "This capability cannot be granted by your role."}</span> : null}</span></label>)}</section>)}
        {role ? (
          <RoleMachineScopeEditor msId={msId} roleId={role.id} />
        ) : checked.has("manage_machines") ? (
          <p className="rounded-md border border-line bg-surface p-3 text-xs text-muted">
            Machine access is limited per role. Save this role, then reopen it to choose which
            machines it can manage — until then it can manage none.
          </p>
        ) : null}
        {save.error && !nameError && !actionsError ? <p className="text-sm text-danger">{save.error.message}</p> : null}
      </div>
    </Modal>
  );
}

function fieldError(value: unknown) {
  if (Array.isArray(value)) return value.join(" ");
  return typeof value === "string" ? value : "";
}
