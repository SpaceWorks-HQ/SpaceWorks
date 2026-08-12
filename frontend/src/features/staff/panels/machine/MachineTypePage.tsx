import { Skeleton, StatusBadge } from "../../../../components/ui";
import { ImageThumbnail } from "../../../../components/ui/ImageThumbnail";
import type { PrinterPool } from "../../../../generated/api";
import { isBuiltinPrinterType } from "../../machinesApi";
import type { Machine, MachineType } from "../../machinesApi";
import { MachineServiceConsole } from "./MachineServiceConsole";
import { PrinterServiceConsole } from "./PrinterServiceConsole";
import { ConsumablePoolList } from "./SharedConsumablesSection";
import type { ServiceDraft } from "./serviceDrafts";

type Props = {
  makerspaceId: number;
  canManage: boolean;
  machineServiceEnabled: boolean;
  printingEnabled: boolean;
  machineType: MachineType;
  allMachines: Machine[];
  visibleMachines: Machine[];
  boundPools: PrinterPool[];
  formPools: PrinterPool[];
  machinesLoading: boolean;
  machinesFailed: boolean;
  onSelectMachine: (machineId: number) => void;
  draft: ServiceDraft;
  setDraft: (update: (draft: ServiceDraft) => ServiceDraft) => void;
};

const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

/** One machine type's whole world: its machines, its bound consumables, its service queue.
 *
 * This replaces the collapsible `MachineTypeSection`. Every content rule that section
 * carried is preserved verbatim, because each was a bug someone already hit:
 * both empty states require a SUCCESSFUL load, and `type_payload.model` is displayed for
 * any type that records one -- the retired printer roster was the only place it was ever
 * shown, and `run_machine_model` reads it.
 */
export function MachineTypePage({
  makerspaceId,
  canManage,
  machineServiceEnabled,
  printingEnabled,
  machineType,
  allMachines,
  visibleMachines,
  boundPools,
  formPools,
  machinesLoading,
  machinesFailed,
  onSelectMachine,
  draft,
  setDraft,
}: Props) {
  return (
    <div className="grid gap-4">
      <section aria-label={`${machineType.name} machines`} className="rounded-xl border border-line bg-panel">
        <div className="hidden grid-cols-[minmax(0,2fr)_auto_auto] gap-3 border-b border-line px-3 py-2 font-mono text-[11px] uppercase tracking-wide text-muted sm:grid">
          <span>Name</span><span>Status</span><span className="text-right">Usage</span>
        </div>
        {machinesLoading ? (
          <div className="grid gap-2 p-3" aria-label={`Loading ${machineType.name} machines`}>
            <Skeleton className="h-14 w-full" />
          </div>
        ) : null}
        {/* Both empty states require a SUCCESSFUL load. A failed machines request also yields an
            empty array with `isLoading` false, and claiming "no machines are registered" beside
            the actual error tells the operator something untrue about their own fleet. */}
        {!machinesLoading && !machinesFailed && !allMachines.length ? (
          <p className="px-3 py-4 text-sm text-muted">No machines are registered for this type.</p>
        ) : null}
        {!machinesLoading && !machinesFailed && allMachines.length > 0 && !visibleMachines.length ? (
          <p className="px-3 py-4 text-sm text-muted">No machines match the selected status.</p>
        ) : null}
        {visibleMachines.map((machine) => (
          <button
            key={machine.id}
            type="button"
            onClick={() => onSelectMachine(machine.id)}
            className={`grid w-full gap-2 border-b border-line px-3 py-3 text-left last:border-b-0 hover:bg-surface sm:grid-cols-[minmax(0,2fr)_auto_auto] sm:items-center sm:gap-3 ${focusRing}`}
          >
            <span className="flex min-w-0 items-center gap-3">
              {machine.image_url ? <ImageThumbnail src={machine.image_url} alt={machine.name} className="h-10 w-10" /> : null}
              <span className="min-w-0">
                <strong className="block truncate text-sm text-ink">{machine.name}</strong>
                <span className="block truncate text-xs text-muted">
                  {[machine.type_payload?.model, machine.location || "No location"].filter(Boolean).join(" · ")}
                </span>
              </span>
            </span>
            <span><StatusBadge status={machine.status} /></span>
            <span className="font-mono text-sm text-muted sm:text-right">{machine.usage_hours} h</span>
          </button>
        ))}
      </section>

      {machineServiceEnabled && canManage ? (
        <>
          {boundPools.length ? (
            <section className="rounded-xl border border-line bg-panel p-3">
              <h3 className="mb-2 text-base font-semibold text-ink">Bound consumables</h3>
              <ConsumablePoolList makerspaceId={makerspaceId} pools={boundPools} />
            </section>
          ) : null}
          {isBuiltinPrinterType(machineType) ? (
            <PrinterServiceConsole makerspaceId={makerspaceId} canManage={canManage} printingEnabled={printingEnabled} machineType={machineType} machines={allMachines} pools={formPools} draft={draft} setDraft={setDraft} />
          ) : (
            <MachineServiceConsole makerspaceId={makerspaceId} canManage={canManage} machineType={machineType} machines={allMachines} pools={formPools} draft={draft} setDraft={setDraft} />
          )}
        </>
      ) : null}
    </div>
  );
}
