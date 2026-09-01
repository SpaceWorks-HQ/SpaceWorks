import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { getRoleMachineScope, setRoleMachineScope, type MachineScopeOption } from "./rolesApi";

/**
 * Which machines a role's "Machines" capability actually reaches.
 *
 * Machine scoping fails closed on the server, so a role granted `manage_machines` with
 * nothing ticked here can manage nothing. That is deliberate, but it makes this editor
 * load-bearing rather than optional — without it the only ways to grant machine access
 * would be the Django `/control/` console (which staff cannot reach) or the shell.
 *
 * Saved separately from the role's capabilities because it needs a role id: a role that
 * does not exist yet has nothing to link to.
 */
export function RoleMachineScopeEditor({ msId, roleId }: { msId: number; roleId: number }) {
  const scope = useQuery({
    queryKey: ["staff", "role-machine-scope", msId, roleId],
    queryFn: () => getRoleMachineScope(msId, roleId),
  });
  const [types, setTypes] = useState<Set<number>>(new Set());
  const [machines, setMachines] = useState<Set<number>>(new Set());
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!scope.data) return;
    setTypes(new Set(scope.data.machine_type_ids));
    setMachines(new Set(scope.data.machine_ids));
  }, [scope.data]);

  const save = useMutation({
    mutationFn: () => setRoleMachineScope(msId, roleId, {
      machine_type_ids: [...types],
      machine_ids: [...machines],
    }),
    onSuccess: () => {
      setSaved(true);
      void scope.refetch();
    },
  });

  if (scope.isLoading) return <p className="text-sm text-muted">Loading machine scope...</p>;
  if (scope.error) return <p className="text-sm text-danger">{scope.error.message}</p>;
  if (!scope.data) return null;

  if (!scope.data.scoping_applies) {
    return (
      <section className="grid gap-2 rounded-md border border-line p-3">
        <h3 className="title-section">Machine scope</h3>
        <p className="text-xs text-muted">
          This role either administers the whole makerspace or grants no machine capability,
          so it is not limited to particular machines.
        </p>
      </section>
    );
  }

  const toggle = (set: Set<number>, apply: (next: Set<number>) => void, id: number) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSaved(false);
    apply(next);
  };
  const nothingSelected = types.size === 0 && machines.size === 0;

  return (
    <section className="grid gap-3 rounded-md border border-line p-3">
      <div className="grid gap-1">
        <h3 className="title-section">Machine scope</h3>
        <p className="text-xs text-muted">
          This role can only manage the machine types and machines ticked here. Ticking a
          type also covers machines of that type added later.
        </p>
      </div>
      {nothingSelected ? (
        <p className="rounded-md border border-line bg-surface p-2 text-xs text-danger">
          Nothing selected — this role currently cannot manage any machine.
        </p>
      ) : null}
      <OptionList
        title="Machine types"
        options={scope.data.available_machine_types}
        selected={types}
        onToggle={(id) => toggle(types, setTypes, id)}
        describe={(option) => (option.is_builtin ? "Built-in" : "This makerspace")}
      />
      <OptionList
        title="Individual machines"
        options={scope.data.available_machines}
        selected={machines}
        onToggle={(id) => toggle(machines, setMachines, id)}
        describe={(option) => (option.is_active === false ? "Retired" : "")}
      />
      <div className="flex items-center justify-end gap-2">
        {saved && !save.isPending ? <span className="text-xs text-muted">Saved</span> : null}
        {save.error ? <span className="text-xs text-danger">{save.error.message}</span> : null}
        <button className="desk-button-primary" type="button" disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving..." : "Save machine scope"}
        </button>
      </div>
    </section>
  );
}

function OptionList({ title, options, selected, onToggle, describe }: {
  title: string;
  options: MachineScopeOption[];
  selected: Set<number>;
  onToggle: (id: number) => void;
  describe: (option: MachineScopeOption) => string;
}) {
  if (!options.length) {
    return (
      <div className="grid gap-1">
        <h4 className="title-section">{title}</h4>
        <span className="text-xs text-muted">None available.</span>
      </div>
    );
  }
  return (
    <div className="grid gap-1">
      <h4 className="title-section">{title}</h4>
      <div className="grid gap-1 sm:grid-cols-2">
        {options.map((option) => {
          const note = describe(option);
          return (
            <label key={option.id} className="flex items-center gap-2 text-sm">
              <input
                className="h-4 w-4 accent-accent"
                type="checkbox"
                checked={selected.has(option.id)}
                onChange={() => onToggle(option.id)}
              />
              <span className="text-ink">{option.label}</span>
              {note ? <span className="text-xs text-muted">{note}</span> : null}
            </label>
          );
        })}
      </div>
    </div>
  );
}
