import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { CollapsibleSection, EmptyState, Skeleton, StatusBadge } from "../../../components/ui";
import { ImageThumbnail } from "../../../components/ui/ImageThumbnail";
import { collectionResults, createMachine, getMachines, getMachineTypes, machineKeys, type MachineStatus } from "../machinesApi";
import { MachineDrawer } from "./machine/MachineDrawer";
import { MachineTypesPanel } from "./MachineTypesPanel";
import { Panel } from "./shared";
import { PrinterServiceConsole } from "./machine/PrinterServiceConsole";
import { MachineServiceConsole } from "./machine/MachineServiceConsole";

type StatusFilter = "all" | MachineStatus;

export function MachinesPanel({ makerspaceId, canManage, canConfigureMachineTypes, maintenanceEnabled }: {
  makerspaceId: number;
  canManage: boolean;
  canConfigureMachineTypes: boolean;
  maintenanceEnabled: boolean;
}) {
  const queryClient = useQueryClient();
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [machineTypeId, setMachineTypeId] = useState("");
  const machines = useQuery({ queryKey: machineKeys.list(makerspaceId), queryFn: () => getMachines(makerspaceId) });
  const machineTypes = useQuery({ queryKey: machineKeys.types(makerspaceId), queryFn: () => getMachineTypes(makerspaceId) });
  const types = collectionResults(machineTypes.data);
  const rows = useMemo(() => (machines.data?.results ?? []).filter((machine) =>
    (typeFilter === "all" || machine.machine_type.id === Number(typeFilter)) &&
    (statusFilter === "all" || machine.status === statusFilter),
  ), [machines.data, statusFilter, typeFilter]);
  // Group by type so a lab reads as "3D Printers (3)" rather than one flat list.
  // Order follows the machine-type list, with any type not in it (a type the row
  // references but the types query has not returned) appended rather than dropped.
  const groups = useMemo(() => {
    const byType = new Map<number, { name: string; icon: string; machines: typeof rows }>();
    for (const machine of rows) {
      const existing = byType.get(machine.machine_type.id);
      if (existing) existing.machines.push(machine);
      else byType.set(machine.machine_type.id, {
        name: machine.machine_type.name, icon: machine.machine_type.icon, machines: [machine],
      });
    }
    const ordered = types.filter((type) => byType.has(type.id)).map((type) => type.id);
    const extra = [...byType.keys()].filter((id) => !ordered.includes(id));
    return [...ordered, ...extra].map((id) => ({ id, ...byType.get(id)! }));
  }, [rows, types]);
  // Visibility and creation authority are different questions: a role linked to one
  // individual machine can see its type but may not add another machine of that kind,
  // so offering every visible type here is offering an action that can only 403.
  const creatableTypes = useMemo(() => types.filter((type) => type.can_create_machine), [types]);
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set());
  const toggleGroup = (id: number) => setCollapsed((current) => {
    const next = new Set(current);
    if (!next.delete(id)) next.add(id);
    return next;
  });

  const create = useMutation({
    mutationFn: () => createMachine(makerspaceId, {
      name: name.trim(), machine_type_id: Number(machineTypeId), location: "", notes: "", firmware_version: "", camera_feed_url: "",
    }),
    onSuccess: async (machine) => {
      setName(""); setMachineTypeId(""); setSelectedId(machine.id);
      await queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) });
    },
  });
  const filtersActive = typeFilter !== "all" || statusFilter !== "all";
  return (
    <Panel title="Machines">
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm text-muted">Manage shared equipment, operators, usage, documents, and operating status.</p>
          {machines.data ? <p className="mt-1 text-xs text-muted">{machines.data.count} machines total</p> : null}
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <label className="grid gap-1 text-xs font-semibold text-muted sm:w-48">
            Type
            <select className="desk-input" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
              <option value="all">All types</option>
              {types.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-semibold text-muted sm:w-44">
            Status
            <select className="desk-input" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
              <option value="all">All statuses</option>
              <option value="idle">Idle</option><option value="running">Running</option><option value="reserved">Reserved</option>
              <option value="maintenance">Maintenance</option><option value="offline">Offline</option>
            </select>
          </label>
        </div>
      </div>
      <MachineTypesPanel makerspaceId={makerspaceId} canConfigureMachineTypes={canConfigureMachineTypes} />
      {canManage && creatableTypes.length ? (
        <form className="mb-4 grid gap-3 rounded-xl border border-line bg-bg p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end"
          onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
          <label className="grid gap-1 text-xs font-semibold text-muted">
            Machine name
            <input className="desk-input" value={name} onChange={(event) => setName(event.target.value)} required />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-muted">
            Machine type
            <select className="desk-input" value={machineTypeId} onChange={(event) => setMachineTypeId(event.target.value)} required>
              <option value="">Select a type</option>
              {creatableTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
            </select>
          </label>
          <button className="desk-button-primary" type="submit" disabled={create.isPending || !name.trim() || !machineTypeId}>
            {create.isPending ? "Creating..." : "New machine"}
          </button>
          {machineTypes.error instanceof Error ? <p className="text-sm text-danger md:col-span-3">{machineTypes.error.message}</p> : null}
          {create.error instanceof Error ? <p className="text-sm text-danger md:col-span-3">{create.error.message}</p> : null}
        </form>
      ) : null}
      {machines.isLoading ? <div className="grid gap-2" aria-label="Loading machines">
        {[0, 1, 2, 3].map((item) => <Skeleton key={item} className="h-16 w-full" />)}
      </div> : null}
      {machines.error instanceof Error ? <p className="mb-3 text-sm text-danger">{machines.error.message}</p> : null}
      {!machines.isLoading && !machines.error && !rows.length ? (
        <EmptyState title={filtersActive ? "No matching machines" : "No machines yet"}
          description={filtersActive ? "Try a different type or status filter." : canManage ? "Create the first machine above." : "No machines are available in this makerspace."} />
      ) : null}
      {groups.length ? (
        <div className="grid gap-3">
          {groups.map((group) => (
            <CollapsibleSection key={group.id} title={group.name} icon={group.icon || null}
              count={group.machines.length} open={!collapsed.has(group.id)}
              onToggle={() => toggleGroup(group.id)}>
              {/* The type column is gone: the section heading already says it. */}
              <div className="hidden grid-cols-[minmax(0,2fr)_auto_auto] gap-3 border-b border-line px-3 py-2 text-xs font-semibold text-muted sm:grid">
                <span>Name</span><span>Status</span><span className="text-right">Usage</span>
              </div>
              {group.machines.map((machine) => (
                <button key={machine.id} type="button" onClick={() => setSelectedId(machine.id)}
                  className="grid w-full gap-2 border-b border-line px-3 py-3 text-left last:border-b-0 hover:bg-surface sm:grid-cols-[minmax(0,2fr)_auto_auto] sm:items-center sm:gap-3">
                  <span className="flex min-w-0 items-center gap-3">
                    {machine.image_url ? <ImageThumbnail src={machine.image_url} alt={machine.name} className="h-10 w-10" /> : null}
                    <span className="min-w-0"><strong className="block truncate text-sm text-ink">{machine.name}</strong><span className="text-xs text-muted">{machine.location || "No location"}</span></span>
                  </span>
                  <span><StatusBadge status={machine.status} /></span>
                  <span className="text-sm text-muted sm:text-right">{machine.usage_hours} h</span>
                </button>
              ))}
            </CollapsibleSection>
          ))}
        </div>
      ) : null}
      <PrinterServiceConsole makerspaceId={makerspaceId} canManage={canManage} />
      <MachineServiceConsole makerspaceId={makerspaceId} canManage={canManage} />
      {selectedId !== null ? (
        <MachineDrawer key={selectedId} machineId={selectedId} makerspaceId={makerspaceId}
          canManageMachines={canManage}
          maintenanceEnabled={maintenanceEnabled}
          onClose={() => setSelectedId(null)} />
      ) : null}
    </Panel>
  );
}
