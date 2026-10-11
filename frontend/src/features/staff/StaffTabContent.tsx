import { Suspense } from "react";

import { Skeleton } from "../../components/ui";
import type { StaffAuthUser } from "../../lib/api";
import { featureEnabled } from "../../lib/features";
import { getStaffAccess } from "./staffAccess";
import { filterTabsByEnabledModules } from "./staffTabs";
import { StaffPlatformTabContent } from "./StaffPlatformTabContent";
import { Panel, type Makerspace } from "./panels/shared";
import { StaffPanelErrorBoundary } from "./StaffPanelErrorBoundary";
import { PlatformDashboardPanel } from "./StaffTabLoaders";

import { PaymentsPanel, DevicesPanel, DashboardPanel, NotificationInbox, DirectLoans, Inventory, Ledger, MachinesPanel, EventsPanel, OrganizedEventsPanel, OrganizationAnalyticsPanel, OrganizationsPanel, BookingsPanel, MembersPanel, MemberCardsPanel, QrTools, RequestsPanel, OperationsReports, AuditLog, BulkImport, ScannerPanel, ContainersPanel, StocktakePanel, StockTransferPanel, ProcurementPanel, WarrantyPanel, AccountabilityPanel, Categories, NeedsFixShelf, HandoverConsole } from "./StaffTabLoaders";

export function StaffTabContent({
  activeMakerspace,
  activeTab,
  guestOnly,
  makerspaces,
  isSuperadmin,
  currentUser,
  onAuthRefresh,
  printingOnly,
  canChooseToBuyKind,
  canEditInventory,
  canIssueDirectLoan,
  canCollectServiceRequests,
  canUseToBuy,
  canManageQr,
  canManageMakerspace,
  canUseMemberCards,
  canManageMachines,
  isMachineOnly,
  canConfigureMachineTypes,
  canManageEvents,
  canManageBookings,
  canSeeHardware,
  canSeePrinting,
  canViewAudit,
  singleTenantLocked = false,
}: {
  activeMakerspace?: Makerspace;
  activeTab: string;
  guestOnly: boolean;
  makerspaces: Makerspace[];
  isSuperadmin: boolean;
  currentUser: StaffAuthUser;
  onAuthRefresh: () => void;
  printingOnly: boolean;
  canChooseToBuyKind: boolean;
  canEditInventory: boolean;
  canIssueDirectLoan: boolean;
  canCollectServiceRequests: boolean;
  canUseToBuy: boolean;
  canManageQr: boolean;
  canManageMakerspace: boolean;
  canUseMemberCards: boolean;
  canManageMachines: boolean;
  isMachineOnly: boolean;
  canConfigureMachineTypes: boolean;
  canManageEvents: boolean;
  canManageBookings: boolean;
  canSeeHardware: boolean;
  canSeePrinting: boolean;
  canViewAudit: boolean;
  // Machines needs this for links; targetless organization panels need it as a mount gate.
  singleTenantLocked?: boolean;
}) {
  if (activeTab === "platform-dashboard" && isSuperadmin && !singleTenantLocked) {
    return <StaffPanelErrorBoundary resetKey="platform-dashboard"><Suspense fallback={<Skeleton className="h-40 w-full" />}><PlatformDashboardPanel /></Suspense></StaffPanelErrorBoundary>;
  }
  if (activeTab === "organizations") {
    return <StaffPanelErrorBoundary resetKey="organizations"><Suspense fallback={<Skeleton className="h-40 w-full" />}><OrganizationsPanel /></Suspense></StaffPanelErrorBoundary>;
  }
  if (!activeMakerspace) {
    return <Panel title="No makerspace">Assign a makerspace to this account.</Panel>;
  }
  const makerspaceKey = activeMakerspace.id;
  const actorActions = currentUser.makerspaces.find((space) => space.id === makerspaceKey)?.actions ?? [];
  const has = (action: string) => isSuperadmin || actorActions.includes(action);
  return (
    <StaffPanelErrorBoundary resetKey={`${makerspaceKey}:${activeTab}`}>
      <Suspense fallback={<div className="p-4"><Skeleton className="h-40 w-full" /></div>}>
      {activeTab === "devices" && (isSuperadmin || currentUser.makerspaces.some(
        (space) => space.id === makerspaceKey && space.actions.includes("manage_devices"),
      )) && activeMakerspace.enabled_modules?.includes("devices") ? (
        <DevicesPanel key={makerspaceKey} makerspaceId={makerspaceKey} />
      ) : null}
      {activeTab === "dashboard" ? (
        <DashboardPanel key={makerspaceKey} makerspace={activeMakerspace} canManageMakerspace={canManageMakerspace} allowedTabs={filterTabsByEnabledModules(getStaffAccess(actorActions, isSuperadmin, singleTenantLocked, isMachineOnly).allowedTabs, activeMakerspace)} singleTenantLocked={singleTenantLocked} guestOnly={guestOnly} />
      ) : null}
      {activeTab === "notifications" ? (
        <NotificationInbox key={makerspaceKey} makerspace={activeMakerspace} />
      ) : null}
      {activeTab === "requests" ? (
        <RequestsPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          guestOnly={guestOnly}
          canSeeHardware={canSeeHardware}
          canViewAudit={canViewAudit}
        />
      ) : null}
      {activeTab === "inventory" ? (
        <Inventory
          key={makerspaceKey}
          makerspace={activeMakerspace}
          canViewAudit={canViewAudit}
          canUseToBuy={canUseToBuy}
        />
      ) : null}
      {activeTab === "needsfix" && canEditInventory ? <NeedsFixShelf key={makerspaceKey} makerspace={activeMakerspace} /> : null}
      {activeTab === "categories" && canEditInventory ? <Categories key={makerspaceKey} makerspace={activeMakerspace} /> : null}      {activeTab === "machines" ? (
        <MachinesPanel
          key={makerspaceKey}
          makerspaceId={activeMakerspace.id}
          canManage={canManageMachines}
          enabledFeatures={activeMakerspace.enabled_features ?? []}
          canConfigureMachineTypes={canConfigureMachineTypes}
          maintenanceEnabled={activeMakerspace.enabled_modules?.includes("maintenance") ?? false}
          machineServiceEnabled={activeMakerspace.enabled_modules?.includes("machine_service") ?? false}
          printingEnabled={activeMakerspace.enabled_modules?.includes("printing") ?? false}
          reportsEnabled={activeMakerspace.enabled_modules?.includes("reports") ?? false}
          guestOnly={guestOnly}
          makerspaceSlug={activeMakerspace.slug}
          singleTenantLocked={singleTenantLocked}
          delegatedRecipientRulesEnabled={
            isMachineOnly &&
            (activeMakerspace.enabled_modules ?? []).includes("notifications") &&
            featureEnabled(
              activeMakerspace.enabled_features ?? [],
              "notifications.delegated_recipients",
            )
          }
        />
      ) : null}
      {activeTab === "events" && canManageEvents ? <EventsPanel key={makerspaceKey} makerspaceId={activeMakerspace.id} /> : null}
      {activeTab === "organized" && !isSuperadmin ? <OrganizedEventsPanel /> : null}
      {activeTab === "organization-analytics" && !isSuperadmin && !singleTenantLocked ? (
        <OrganizationAnalyticsPanel makerspaces={makerspaces} />
      ) : null}
      {activeTab === "bookings" && canManageBookings ? <BookingsPanel key={makerspaceKey} makerspaceId={activeMakerspace.id} /> : null}
      {activeTab === "members" && has("manage_members") ? (
        <MembersPanel
          key={makerspaceKey}
          makerspaceId={activeMakerspace.id}
          membershipEnabled={(activeMakerspace.enabled_modules ?? []).includes("membership")}
          canManageMakerspace={canManageMakerspace}
          canViewFinance={has("view_finance")}
          canRecordPayment={has("record_payment")}
        />
      ) : null}
      {activeTab === "cards" && canUseMemberCards ? (
        <MemberCardsPanel key={makerspaceKey} makerspaceId={activeMakerspace.id} />
      ) : null}
      {activeTab === "payments" && (has("view_finance") || has("record_payment")) ? <PaymentsPanel key={makerspaceKey} makerspaceId={activeMakerspace.id} actorActions={actorActions} isSuperadmin={isSuperadmin} /> : null}
      {activeTab === "tobuy" ? (
        <ProcurementPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          canChooseKind={canChooseToBuyKind}
        />
      ) : null}
      {activeTab === "transfers" && (canEditInventory || isSuperadmin) ? (
        <StockTransferPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          makerspaces={makerspaces}
          isSuperadmin={isSuperadmin}
          canEditInventory={canEditInventory}
        />
      ) : null}
      {activeTab === "stocktake" && canEditInventory ? <StocktakePanel key={makerspaceKey} makerspace={activeMakerspace} isSuperadmin={isSuperadmin} canConfigure={canManageMakerspace} /> : null}
      {activeTab === "containers" && canManageQr ? <ContainersPanel key={makerspaceKey} makerspace={activeMakerspace} canEditInventory={canEditInventory} /> : null}
      {activeTab === "ledger" ? (
        <Ledger
          key={makerspaceKey}
          makerspace={activeMakerspace}
          isSuperadmin={isSuperadmin}
        />
      ) : null}
      {activeTab === "warranty" && (canEditInventory || canSeePrinting) ? (
        <WarrantyPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          canEditInventory={canEditInventory}
        />
      ) : null}
      {activeTab === "accountability" && canViewAudit ? (
        <AccountabilityPanel key={makerspaceKey} makerspace={activeMakerspace} isSuperadmin={isSuperadmin} />
      ) : null}
      {activeTab === "reports" ? (
        <OperationsReports
          key={makerspaceKey}
          makerspace={activeMakerspace}
          makerspaces={makerspaces}
          isSuperadmin={isSuperadmin}
          printingOnly={printingOnly}
          canViewAudit={canViewAudit}
          canManageMachines={canManageMachines}
          canViewFinance={has("view_finance")}
        />
      ) : null}
      {activeTab === "direct" && canIssueDirectLoan ? <DirectLoans key={makerspaceKey} makerspace={activeMakerspace} /> : null}
      {activeTab === "handover" && canCollectServiceRequests ? (
        <HandoverConsole key={makerspaceKey} makerspaceId={makerspaceKey} enabled />
      ) : null}
      {activeTab === "bulk" && canEditInventory ? <BulkImport key={makerspaceKey} makerspace={activeMakerspace} /> : null}
      {activeTab === "qr" && canManageQr ? <QrTools key={makerspaceKey} makerspace={activeMakerspace} /> : null}
      {activeTab === "scanner" && canManageQr ? (
        <ScannerPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          isSuperadmin={isSuperadmin}
          makerspaces={makerspaces}
        />
      ) : null}
      <StaffPlatformTabContent activeTab={activeTab} activeMakerspace={activeMakerspace} makerspaces={makerspaces} isSuperadmin={isSuperadmin} canManageMakerspace={canManageMakerspace} currentUser={currentUser} onAuthRefresh={onAuthRefresh} />
      {activeTab === "audit" && canViewAudit ? <AuditLog makerspaceId={activeMakerspace?.id} /> : null}
      </Suspense>
    </StaffPanelErrorBoundary>
  );
}
