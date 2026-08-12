import { useMemo, useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { PrinterPool } from "../../../generated/api";
import { collectionResults, createMachine, getMachines, getMachineTypes, isBuiltinPrinterType, machineKeys, type MachineStatus, type MachineType } from "../machinesApi";
import { machineTypeSegment, parseMachineTypeSegment, staffSubPathFromPath, staffTabPath } from "../staffTabs";
import { MachineDrawer } from "./machine/MachineDrawer";
import { MachineTypeCards } from "./machine/MachineTypeCards";
import { MachineTypePage } from "./machine/MachineTypePage";
import { SharedConsumablesSection } from "./machine/SharedConsumablesSection";
import { poolPath, poolQueryKey } from "./machine/servicePools";
import { useServiceDrafts } from "./machine/serviceDrafts";
import { MachineTypesPanel } from "./MachineTypesPanel";
import { NotificationRecipientPicker } from "../NotificationRecipientPicker";
import { Panel, useStaffGet } from "./shared";

type StatusFilter = "all" | MachineStatus;

type Props = {
  makerspaceId: number;
  canManage: boolean;
  canConfigureMachineTypes: boolean;
  maintenanceEnabled: boolean;
  machineServiceEnabled: boolean;
  printingEnabled: boolean;
  delegatedRecipientRulesEnabled: boolean;
  guestOnly?: boolean;
  makerspaceSlug?: string | null;
  singleTenantLocked?: boolean;
};

const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export function MachinesPanel({
  makerspaceId,
  canManage,
  canConfigureMachineTypes,
  maintenanceEnabled,
  machineServiceEnabled,
  printingEnabled,
  delegatedRecipientRulesEnabled,
  guestOnly = false,
  makerspaceSlug = null,
  singleTenantLocked = false,
}: Props) {
  const queryClient = useQueryClient();
  const location = useLocation();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sharedOpen, setSharedOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [machineTypeId, setMachineTypeId] = useState("");
  const [model, setModel] = useState("");
  // Lives HERE, in the container that survives index-to-type navigation, not in
  // `MachineTypePage`. Only one type is mounted at a time now, so a hook inside the page
  // would discard a half-typed service form on every navigation -- the drafts previously
  // survived section collapse for exactly that reason.
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
  // stale, or omit a type while machines of it loaded fine. Building the index from `types`
  // alone then makes those machines VANISH. Nested `machine.machine_type` is the fallback and
  // is display-only: it carries no `can_create_machine`, which correctly reads as no creation
  // authority. It is still NAVIGABLE -- the machines list is server-scoped too, so a machine
  // the server returned implies a type this actor may open.
  const reachableTypes = useMemo(() => {
    const known = new Set(types.map((type) => type.id));
    const extras: MachineType[] = [];
    for (const machine of allMachines) {
      if (known.has(machine.machine_type.id)) continue;
      known.add(machine.machine_type.id);
      extras.push(machine.machine_type);
    }
    return [...types, ...extras];
  }, [allMachines, types]);
  const creatableTypes = useMemo(() => types.filter((type) => type.can_create_machine === true), [types]);

  const hrefFor = (machineType: MachineType) =>
    staffTabPath("machines", guestOnly, makerspaceSlug, singleTenantLocked, machineTypeSegment(machineType));
  const indexHref = staffTabPath("machines", guestOnly, makerspaceSlug, singleTenantLocked);

  const requestedTypeId = parseMachineTypeSegment(staffSubPathFromPath(location.pathname, guestOnly));
  // Both server-scoped sources must have SETTLED SUCCESSFULLY before an id can be called
  // unreachable. Judging on the type query alone would bounce a type known only through the
  // nested fallback; judging while either is loading would bounce every direct link on first
  // paint; judging after a failure would turn a network blip into what looks like a revoked
  // permission.
  const sourcesSettled =
    !machineTypes.isLoading && !machineTypes.isError && !machines.isLoading && !machines.isError;
  const selectedType = reachableTypes.find((type) => type.id === requestedTypeId) ?? null;
  const unknownType = requestedTypeId !== null && sourcesSettled && !selectedType;

  // NO auto-redirect when a single type is reachable. Redirecting would make this index --
  // and with it machine creation, machine-type configuration, shared consumable pools and
  // the delegated recipient picker -- permanently unreachable for exactly the scoped
  // maintainer those controls are meant for. A single-type actor gets that type's page
  // rendered inline below instead, which lands them on their machines without hiding
  // anything, and removes the redirect loop and the flash-redirect at the same time.
  const soleType = reachableTypes.length === 1 ? reachableTypes[0] : null;
  const shownType = selectedType ?? (requestedTypeId === null ? soleType : null);

  const wantsModel = isBuiltinPrinterType(creatableTypes.find((type) => type.id === Number(machineTypeId)));
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

  // Normalise an unknown or unreachable type id back to the index -- the console's existing
  // behaviour for a stale deep link, rather than a dead denial page. `replace` so the bad
  // URL does not sit in history waiting for the back button.
  if (unknownType) {
    return <Navigate replace to={indexHref} />;
  }

  // A deep link whose type is known only through the nested machines fallback resolves once
  // the machines query lands. Rendering the index in the meantime would flash the card grid
  // in front of someone who asked for one specific type, so hold with a skeleton instead --
  // an honest "still resolving", which is also what stops the redirect above from firing
  // early.
  if (requestedTypeId !== null && !selectedType && !sourcesSettled) {
    return (
      <Panel title="Machines">
        <div className="h-40 animate-pulse rounded-xl border border-line bg-surface" aria-label="Loading machine type" />
      </Panel>
    );
  }

  const typeMachines = shownType
    ? allMachines.filter((machine) => machine.machine_type.id === shownType.id)
    : [];
  const machineIds = new Set(typeMachines.map((machine) => machine.id));
  const boundPools = pools.filter((pool) => pool.machine_id !== null && machineIds.has(pool.machine_id));
  const onTypePage = shownType !== null && selectedType !== null;

  return (
    <Panel title={shownType ? shownType.name : "Machines"}>
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          {onTypePage ? (
            <Link className={`mb-1 inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-wide text-accent-ink hover:underline ${focusRing}`} to={indexHref}>
              ← All machine types
            </Link>
          ) : null}
          <p className="text-sm text-muted">
            {shownType
              ? `Machines, consumables and the service queue for ${shownType.name}.`
              : "Manage shared equipment, operators, usage, documents, and operating status."}
          </p>
          {machines.data && !shownType ? (
            <p className="mt-1 font-mono text-xs text-muted">{machines.data.count} machines total</p>
          ) : null}
        </div>
        {shownType ? (
          <label className="grid gap-1 font-mono text-[11px] uppercase tracking-wide text-muted sm:w-44">
            Status
            <select className={`desk-input ${focusRing}`} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
              <option value="all">All statuses</option>
              <option value="idle">Idle</option><option value="running">Running</option><option value="reserved">Reserved</option>
              <option value="maintenance">Maintenance</option><option value="offline">Offline</option>
            </select>
          </label>
        ) : null}
      </div>

      {machineTypes.error instanceof Error ? <p className="mb-3 text-sm text-danger">{machineTypes.error.message}</p> : null}
      {machines.error instanceof Error ? <p className="mb-3 text-sm text-danger">{machines.error.message}</p> : null}
      {/* Panel level, not inside the Shared section: pools feed every type's start and
          manual-usage forms, and Shared may be collapsed. A failed load would otherwise hand
          those forms an empty selector with no indication stock failed to fetch, and an
          operator would retry a start that cannot succeed. */}
      {poolQuery.error instanceof Error ? (
        <p className="mb-3 text-sm text-danger">Consumable pools could not be loaded: {poolQuery.error.message}</p>
      ) : null}

      {shownType ? (
        <MachineTypePage
          makerspaceId={makerspaceId}
          canManage={canManage}
          machineServiceEnabled={machineServiceEnabled}
          printingEnabled={printingEnabled}
          machineType={shownType}
          allMachines={typeMachines}
          visibleMachines={typeMachines.filter((machine) => statusFilter === "all" || machine.status === statusFilter)}
          boundPools={boundPools}
          formPools={[...sharedPools, ...boundPools]}
          machinesLoading={machines.isLoading}
          machinesFailed={machines.isError}
          onSelectMachine={setSelectedId}
          draft={draftFor(shownType.id)}
          setDraft={(update) => setDraft(shownType.id, update)}
        />
      ) : (
        <MachineTypeCards
          machineTypes={reachableTypes}
          machines={allMachines}
          machinesLoading={machines.isLoading}
          machinesFailed={machines.isError}
          typesLoading={machineTypes.isLoading}
          typesFailed={machineTypes.isError}
          hrefFor={hrefFor}
        />
      )}

      {/* The settings block. Rendered on the index AND beneath a sole type's page, which is
          what makes "land straight on my type" safe: none of these controls can become
          unreachable for an actor who only ever has one type. */}
      {!onTypePage ? (
        <div className="mt-4 grid gap-4 border-t border-line pt-4">
          <MachineTypesPanel makerspaceId={makerspaceId} canConfigureMachineTypes={canConfigureMachineTypes} />

          {maintenanceEnabled && delegatedRecipientRulesEnabled ? (
            <NotificationRecipientPicker delegated makerspaceId={makerspaceId} />
          ) : null}

          {canManage && creatableTypes.length > 0 ? (
            <form className="grid gap-3 rounded-xl border border-line bg-bg p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
              <label className="grid gap-1 font-mono text-[11px] uppercase tracking-wide text-muted">
                Machine name
                <input className={`desk-input ${focusRing}`} value={name} onChange={(event) => setName(event.target.value)} required />
              </label>
              <label className="grid gap-1 font-mono text-[11px] uppercase tracking-wide text-muted">
                Machine type
                <select className={`desk-input ${focusRing}`} value={machineTypeId} onChange={(event) => setMachineTypeId(event.target.value)} required>
                  <option value="">Select a type</option>
                  {creatableTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
                </select>
              </label>
              {/* The retired printer roster was the ONLY surface that recorded a printer's model,
                  and `run_machine_model` plus the printer reports read it -- dropping the field
                  would leave it permanently blank for every newly created printer. */}
              {wantsModel ? (
                <label className="grid gap-1 font-mono text-[11px] uppercase tracking-wide text-muted md:col-span-2">
                  Printer model
                  <input className={`desk-input ${focusRing}`} value={model} onChange={(event) => setModel(event.target.value)} placeholder="e.g. Prusa MK4" />
                </label>
              ) : null}
              <button className={`desk-button-primary ${focusRing}`} type="submit" disabled={create.isPending || !name.trim() || !machineTypeId}>{create.isPending ? "Creating..." : "New machine"}</button>
              {create.error instanceof Error ? <p className="text-sm text-danger md:col-span-3">{create.error.message}</p> : null}
            </form>
          ) : null}

          {canManage && machineServiceEnabled ? (
            <SharedConsumablesSection makerspaceId={makerspaceId} pools={sharedPools} poolError={poolQuery.error} open={sharedOpen} onToggle={() => setSharedOpen((current) => !current)} />
          ) : null}
        </div>
      ) : null}

      {selectedId !== null ? <MachineDrawer key={selectedId} machineId={selectedId} makerspaceId={makerspaceId} canManageMachines={canManage} maintenanceEnabled={maintenanceEnabled} onClose={() => setSelectedId(null)} /> : null}
    </Panel>
  );
}
