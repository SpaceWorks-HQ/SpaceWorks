import { Link, Navigate, useLocation } from "react-router-dom";

import { StaffHeader } from "./StaffHeader";
import { StaffSidebar } from "./StaffSidebar";
import { StaffTabContent } from "./StaffTabContent";
import { EmptyState } from "../../components/ui/EmptyState";
import { SkipLink } from "../../components/SkipLink";
import { getStaffAccess, STAFF_TAB_KEYS, TAB_LABELS } from "./staffAccess";
import {
  filterTabsByEnabledModules,
  readStoredStaffTab,
  staffTabPath,
  tabFromStaffPath,
} from "./staffTabs";
import type { StaffAuthUser } from "../../lib/api";
import type { Makerspace } from "./panels/shared";

export function StaffWorkspace({
  activeMakerspace,
  actions,
  canConfigureMachineTypes,
  collapsedGroups,
  guestOnly,
  isSuperadmin,
  makerspaces,
  onAuthRefresh,
  selected,
  setSelected,
  setTab,
  signOut,
  singleTenantLocked,
  toggleGroup,
  user,
}: {
  activeMakerspace?: Makerspace;
  actions: readonly string[];
  canConfigureMachineTypes: boolean;
  collapsedGroups: Set<string>;
  guestOnly: boolean;
  isSuperadmin: boolean;
  makerspaces: Makerspace[];
  onAuthRefresh: () => void;
  selected: number | null;
  setSelected: (id: number | null) => void;
  setTab: (tab: string) => void;
  signOut: () => Promise<void>;
  singleTenantLocked: boolean;
  toggleGroup: (label: string) => void;
  user: StaffAuthUser;
}) {
  const location = useLocation();
  const {
    allowedTabs,
    canChooseToBuyKind,
    canEditInventory,
    canIssueDirectLoan,
    canCollectServiceRequests,
    canManageMakerspace,
    canManageEvents,
    canManageBookings,
    canManageMachines,
    canManageQr,
    canSeeHardware,
    canSeePrinting,
    canUseToBuy,
    canViewAudit,
    defaultTab,
    handoutOnly,
    printingOnly,
  } = getStaffAccess(actions, isSuperadmin, singleTenantLocked);
  const visibleMakerspaces =
    singleTenantLocked && activeMakerspace
      ? [activeMakerspace]
      : makerspaces;
  const moduleAllowedTabs = filterTabsByEnabledModules(allowedTabs, activeMakerspace);
  const routeTab = tabFromStaffPath(location.pathname, guestOnly);
  const routeTabDenied =
    !!routeTab && STAFF_TAB_KEYS.includes(routeTab) && !moduleAllowedTabs.includes(routeTab);
  const requestedTab = routeTab || readStoredStaffTab();
  const activeTab = moduleAllowedTabs.includes(requestedTab)
    ? requestedTab
    : moduleAllowedTabs.includes(defaultTab)
      ? defaultTab
      : moduleAllowedTabs[0] ?? defaultTab;
  const activeTabPath = activeTab
    ? staffTabPath(activeTab, guestOnly, activeMakerspace?.slug, singleTenantLocked)
    : staffTabPath(defaultTab, guestOnly, activeMakerspace?.slug, singleTenantLocked);

  if (!routeTabDenied && location.pathname !== activeTabPath) {
    return <Navigate replace to={activeTabPath} />;
  }

  return (
    <main className="desk-shell grid grid-cols-1 lg:grid-cols-[260px_minmax(0,1fr)]">
      <SkipLink />
      <StaffSidebar
        activeMakerspace={activeMakerspace}
        activeTab={routeTabDenied ? "" : activeTab}
        allowedTabs={moduleAllowedTabs}
        collapsedGroups={collapsedGroups}
        guestOnly={guestOnly}
        isSuperadmin={isSuperadmin}
        makerspaces={makerspaces}
        printingOnly={printingOnly}
        selected={selected}
        setSelected={setSelected}
        setTab={setTab}
        singleTenantLocked={singleTenantLocked}
        toggleGroup={toggleGroup}
      />

      <section className="min-w-0">
        <StaffHeader
          activeMakerspace={activeMakerspace}
          isSuperadmin={isSuperadmin}
          onSignOut={signOut}
          onSwitchMakerspace={() => setSelected(null)}
          singleTenantLocked={singleTenantLocked}
          user={user}
        />

        <div className="min-w-0 p-5" id="main-content" tabIndex={-1}>
          {routeTabDenied ? (
            <EmptyState
              title="Access denied"
              description="You don't have permission to view this page, or it isn't enabled for this makerspace."
              action={
                <Link className="desk-button-primary" to={activeTabPath}>
                  Go to {TAB_LABELS[activeTab] ?? "your workspace"}
                </Link>
              }
            />
          ) : (
            <StaffTabContent
              activeMakerspace={activeMakerspace}
              activeTab={activeTab}
              guestOnly={guestOnly || handoutOnly}
              makerspaces={visibleMakerspaces}
              isSuperadmin={isSuperadmin}
              currentUser={user}
              onAuthRefresh={onAuthRefresh}
              printingOnly={printingOnly}
              canChooseToBuyKind={canChooseToBuyKind}
              canEditInventory={canEditInventory}
              canIssueDirectLoan={canIssueDirectLoan}
              canCollectServiceRequests={canCollectServiceRequests}
              canUseToBuy={canUseToBuy}
              canManageQr={canManageQr}
              canManageMakerspace={canManageMakerspace}
              canManageEvents={canManageEvents}
              canManageBookings={canManageBookings}
              canManageMachines={canManageMachines}
              canConfigureMachineTypes={canConfigureMachineTypes}
              canSeeHardware={canSeeHardware}
              canSeePrinting={canSeePrinting}
              canViewAudit={canViewAudit}
            />
          )}
        </div>
      </section>
    </main>
  );
}
