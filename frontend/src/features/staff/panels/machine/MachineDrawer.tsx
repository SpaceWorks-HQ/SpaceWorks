import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { DetailDrawer, EmptyState, Skeleton, StatusBadge } from "../../../../components/ui";
import { getMachine, machineKeys } from "../../machinesApi";
import { ConsumablesTab } from "./ConsumablesTab";
import { DocumentsTab } from "./DocumentsTab";
import { ErrorsTab } from "./ErrorsTab";
import { MaintenanceTab } from "./MaintenanceTab";
import { OperatorsTab } from "./OperatorsTab";
import { OverviewTab } from "./OverviewTab";
import { UsageTab } from "./UsageTab";
import { WarrantyTab } from "./WarrantyTab";

const BASE_TABS = ["Overview", "Operators", "Consumables", "Usage", "Documents", "Errors"] as const;
type MachineTab = (typeof BASE_TABS)[number] | "Maintenance" | "Warranty";

export function MachineDrawer({
  machineId, makerspaceId, canManageMachines, maintenanceEnabled, onClose,
}: {
  machineId: number;
  makerspaceId: number;
  canManageMachines: boolean;
  maintenanceEnabled: boolean;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<MachineTab>("Overview");
  const machine = useQuery({
    queryKey: machineKeys.detail(machineId),
    queryFn: () => getMachine(machineId),
  });
  const details = machine.data;
  const maintenanceAllowed = maintenanceEnabled && details?.can_operate === true;
  const tabs: readonly MachineTab[] = [
    ...BASE_TABS.slice(0, 4),
    ...(maintenanceAllowed ? ["Maintenance" as const] : []),
    ...BASE_TABS.slice(4),
    ...(details?.can_edit ? ["Warranty" as const] : []),
  ];

  return (
    <DetailDrawer open title={details?.name ?? "Machine details"} onClose={onClose}>
      {machine.isLoading ? (
        <div className="grid gap-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : null}
      {machine.error instanceof Error ? (
        <EmptyState title="Unable to load machine" description={machine.error.message} />
      ) : null}
      {details ? (
        <div className="grid gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={details.status} />
            {!details.is_active ? (
              <span className="rounded-md bg-warn/15 px-2 py-1 text-xs font-medium text-warn-ink">Retired</span>
            ) : null}
            <span className="text-sm text-muted">
              {details.machine_type.name} · {details.usage_hours} total hours
            </span>
          </div>
          <div className="overflow-x-auto border-b border-line" role="tablist" aria-label="Machine details">
            <div className="flex min-w-max gap-1">
              {tabs.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab}
                  className={activeTab === tab ? "desk-button-primary" : "desk-button-ghost"}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab}
                </button>
              ))}
            </div>
          </div>
          <div role="tabpanel">
            {activeTab === "Overview" ? (
              <OverviewTab
                machine={details}
                makerspaceId={makerspaceId}
                canManageMachines={canManageMachines}
                canEdit={details.can_edit}
                canOperate={details.can_operate}
                canRetire={details.can_retire}
                canUnretire={details.can_unretire}
              />
            ) : null}
            {activeTab === "Operators" ? (
              <OperatorsTab machineId={machineId} canDelegate={details.can_delegate} />
            ) : null}
            {activeTab === "Consumables" ? (
              <ConsumablesTab machineId={machineId} canEdit={details.can_edit}
                canOperate={details.can_operate} />
            ) : null}
            {activeTab === "Usage" ? (
              <UsageTab machineId={machineId} makerspaceId={makerspaceId} canOperate={details.can_operate} />
            ) : null}
            {activeTab === "Maintenance" && maintenanceAllowed ? (
              <MaintenanceTab
                makerspaceId={makerspaceId}
                machineId={machineId}
                canEdit={details.can_edit}
                canOperate={details.can_operate}
                enabled={activeTab === "Maintenance" && maintenanceAllowed}
                retired={!details.is_active}
              />
            ) : null}
            {activeTab === "Documents" ? (
              <DocumentsTab machineId={machineId} canEdit={details.can_edit} />
            ) : null}
            {activeTab === "Errors" ? (
              <ErrorsTab machineId={machineId} canOperate={details.can_operate} />
            ) : null}
            {activeTab === "Warranty" && details.can_edit ? (
              <WarrantyTab machineId={machineId} />
            ) : null}
          </div>
        </div>
      ) : null}
    </DetailDrawer>
  );
}
