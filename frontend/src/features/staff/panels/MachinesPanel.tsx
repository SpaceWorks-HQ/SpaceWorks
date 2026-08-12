import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "../../../components/ui";
import type { PrinterPool } from "../../../generated/api";
import { collectionResults, createMachine, getMachines, getMachineTypes, isBuiltinPrinterType, machineKeys, type MachineStatus, type MachineType } from "../machinesApi";
import { MachineDrawer } from "./machine/MachineDrawer";
import { MachineTypeSection } from "./machine/MachineTypeSection";
import { SharedConsumablesSection } from "./machine/SharedConsumablesSection";
import { poolPath, poolQueryKey } from "./machine/servicePools";
import { useServiceDrafts } from "./machine/serviceDrafts";
import { MachineTypesPanel } from "./MachineTypesPanel";
import { Panel, useStaffGet } from "./shared";

type StatusFilter = "all" | MachineStatus;

type Props = {
  makerspaceId: number;
  canManage: boolean;
  canConfigureMachineTypes: boolean;
  maintenanceEnabled: boolean;
  machineServiceEnabled: boolean;
  printingEnabled: boolean;
};

const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export function MachinesPanel({ makerspaceId, canManage, canConfigureMachineTypes, maintenanceEnabled, machineServiceEnabled, printingEnabled }: Props) {
  const queryClient = useQueryClient();
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [machineTypeId, setMachineTypeId] = useState("");
  const [model, setModel] = useState("");
  const [openTypeIds, setOpenTypeIds] = useState<ReadonlySet<number>>(new Set());
  const [sharedOpen, setSharedOpen] = useState(false);
  const initialSectionOpened = useRef(false);
  const { draftFor, setDraft } = useServiceDrafts();

  const machines = useQuery({ queryKey: machineKeys.list(makerspaceId), queryFn: () => getMachines(makerspaceId) });
  const machineTypes = useQuery({ queryKey: machineKeys.types(makerspaceId), queryFn: () => getMachineTypes(makerspaceId) });
  const poolQuery = useStaffGet<PrinterPool[]>(
    poolQueryKey(makerspaceId),
    poolPath(makerspaceId),
    canManage && machineServiceEnabled,
  );
  const types = collectionResults(machineTypes.data);
  const allMachines = machines.data?.results ?? [];
  const pools = poolQuery.data ?? [];
  const sharedPools = useMemo(() => pools.filter((pool) => pool.machine_id === null), [pools]);
  // The machine and machine-type requests are independent, so the type response can fail, go
  // stale, or omit a type while machines of it loaded fine. Building sections from `types` alone
  // then makes those machines VANISH -- the grouping this replaced deliberately appended such
  // types rather than dropping them. Nested `machine.machine_type` is the fallback, display-only:
  // it carries no `can_create_machine`, which correctly reads as no creation authority.
  const sectionTypes = useMemo(() => {
    const known = new Set(types.map((type) => type.id));
    const extras: MachineType[] = [];
    for (const machine of allMachines) {
      if (known.has(machine.machine_type.id)) continue;
      known.add(machine.machine_type.id);
      extras.push(machine.machine_type);
    }
    return [...types, ...extras];
  }, [allMachines, types]);
  const visibleTypes = useMemo(
    () => sectionTypes.filter((type) => typeFilter === "all" || type.id === Number(typeFilter)),
    [sectionTypes, typeFilter],
  );
  const creatableTypes = useMemo(() => types.filter((type) => type.can_create_machine === true), [types]);

  useEffect(() => {
    if (initialSectionOpened.current || machineTypes.data === undefined) return;
    initialSectionOpened.current = true;
    if (visibleTypes[0]) setOpenTypeIds(new Set([visibleTypes[0].id]));
    else if (canManage && machineServiceEnabled) setSharedOpen(true);
  }, [canManage, machineServiceEnabled, machineTypes.data, visibleTypes]);

  const toggleType = (id: number) => setOpenTypeIds((current) => {
    const next = new Set(current);
    if (!next.delete(id)) next.add(id);
    return next;
  });
  // The retired printer roster was the ONLY surface that recorded a printer's model, and
  // `run_machine_model` plus the printer reports read it -- dropping the field would leave it
  // permanently blank for every newly created printer. It is printer-specific, so it is offered
  // only when the chosen type is one, and sent only when non-empty.
  const selectedType = creatableTypes.find((type) => type.id === Number(machineTypeId));
  const wantsModel = isBuiltinPrinterType(selectedType);
  const create = useMutation({
    mutationFn: () => createMachine(makerspaceId, {
      name: name.trim(),
      machine_type_id: Number(machineTypeId),
      location: "",
      notes: "",
      firmware_version: "",
      camera_feed_url: "",
      ...(wantsModel && model.trim() ? { type_payload: { model: model.trim() } } : {}),
    }),
    onSuccess: async (machine) => {
      setName("");
      setMachineTypeId("");
      setModel("");
      setSelectedId(machine.id);
      await queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) });
    },
  });

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
            <select className={`desk-input ${focusRing}`} value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
              <option value="all">All types</option>
              {types.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-semibold text-muted sm:w-44">
            Status
            <select className={`desk-input ${focusRing}`} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
              <option value="all">All statuses</option>
              <option value="idle">Idle</option><option value="running">Running</option><option value="reserved">Reserved</option>
              <option value="maintenance">Maintenance</option><option value="offline">Offline</option>
            </select>
          </label>
        </div>
      </div>

      <MachineTypesPanel makerspaceId={makerspaceId} canConfigureMachineTypes={canConfigureMachineTypes} />

      {canManage && creatableTypes.length > 0 ? (
        <form className="mb-4 grid gap-3 rounded-xl border border-line bg-bg p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
          <label className="grid gap-1 text-xs font-semibold text-muted">
            Machine name
            <input className={`desk-input ${focusRing}`} value={name} onChange={(event) => setName(event.target.value)} required />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-muted">
            Machine type
            <select className={`desk-input ${focusRing}`} value={machineTypeId} onChange={(event) => setMachineTypeId(event.target.value)} required>
              <option value="">Select a type</option>
              {creatableTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
            </select>
          </label>
          {wantsModel ? (
            <label className="grid gap-1 text-xs font-semibold text-muted md:col-span-2">
              Printer model
              <input className={`desk-input ${focusRing}`} value={model} onChange={(event) => setModel(event.target.value)} placeholder="e.g. Prusa MK4" />
            </label>
          ) : null}
          <button className={`desk-button-primary ${focusRing}`} type="submit" disabled={create.isPending || !name.trim() || !machineTypeId}>{create.isPending ? "Creating..." : "New machine"}</button>
          {create.error instanceof Error ? <p className="text-sm text-danger md:col-span-3">{create.error.message}</p> : null}
        </form>
      ) : null}

      {machineTypes.error instanceof Error ? <p className="mb-3 text-sm text-danger">{machineTypes.error.message}</p> : null}
      {machines.error instanceof Error ? <p className="mb-3 text-sm text-danger">{machines.error.message}</p> : null}
      {/* Panel level, not inside the Shared section: pools feed every type's start and
          manual-usage forms, and Shared may be collapsed. A failed load would otherwise hand
          those forms an empty selector with no indication stock failed to fetch, and an
          operator would retry a start that cannot succeed. */}
      {poolQuery.error instanceof Error ? (
        <p className="mb-3 text-sm text-danger">Consumable pools could not be loaded: {poolQuery.error.message}</p>
      ) : null}
      {!machineTypes.isLoading && !machineTypes.error && !visibleTypes.length ? (
        <EmptyState title="No machine types available" description={typeFilter === "all" ? "No reachable machine types are configured." : "The selected machine type is no longer available."} />
      ) : null}

      <div className="grid gap-3">
        {visibleTypes.map((machineType) => {
          const typeMachines = allMachines.filter((machine) => machine.machine_type.id === machineType.id);
          const visibleMachines = typeMachines.filter((machine) => statusFilter === "all" || machine.status === statusFilter);
          const machineIds = new Set(typeMachines.map((machine) => machine.id));
          const boundPools = pools.filter((pool) => pool.machine_id !== null && machineIds.has(pool.machine_id));
          return (
            <MachineTypeSection
              key={machineType.id}
              makerspaceId={makerspaceId}
              canManage={canManage}
              machineServiceEnabled={machineServiceEnabled}
              printingEnabled={printingEnabled}
              machineType={machineType}
              allMachines={typeMachines}
              visibleMachines={visibleMachines}
              boundPools={boundPools}
              formPools={[...sharedPools, ...boundPools]}
              machinesLoading={machines.isLoading}
              machinesFailed={machines.isError}
              open={openTypeIds.has(machineType.id)}
              onToggle={() => toggleType(machineType.id)}
              onSelectMachine={setSelectedId}
              draft={draftFor(machineType.id)}
              setDraft={(update) => setDraft(machineType.id, update)}
            />
          );
        })}
        {canManage && machineServiceEnabled ? <SharedConsumablesSection makerspaceId={makerspaceId} pools={sharedPools} poolError={poolQuery.error} open={sharedOpen} onToggle={() => setSharedOpen((current) => !current)} /> : null}
      </div>

      {selectedId !== null ? <MachineDrawer key={selectedId} machineId={selectedId} makerspaceId={makerspaceId} canManageMachines={canManage} maintenanceEnabled={maintenanceEnabled} onClose={() => setSelectedId(null)} /> : null}
    </Panel>
  );
}
