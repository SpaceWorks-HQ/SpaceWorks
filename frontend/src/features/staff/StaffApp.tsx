import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ChangePasswordGate } from "./ChangePasswordGate";
import { LoginPanel } from "./LoginPanel";
import { MakerspacePicker } from "./MakerspacePicker";
import { StaffAccessDenied } from "./StaffAccessDenied";
import { StaffWorkspace } from "./StaffWorkspace";
import { RecoveryQuarantinePanel } from "./RecoveryQuarantinePanel";
import { useStaffSession } from "./useStaffSession";
import { tabFromStaffPath } from "./staffTabs";
import { useLocation } from "react-router-dom";

function StaffLoading({ message, restoring = false }: { message: string; restoring?: boolean }) {
  const panelClass = restoring
    ? "desk-panel flex w-full max-w-md flex-col items-center gap-4 p-8 text-center text-sm font-semibold text-muted"
    : "desk-panel w-full max-w-md p-6 text-sm font-semibold text-muted";
  return (
    <main className="desk-shell grid place-items-center px-5">
      <div className={panelClass}>
        <SpaceWorksBadge className={restoring ? undefined : "mb-5"} />
        <span>{message}</span>
      </div>
    </main>
  );
}

export function StaffApp({ guestOnly = false }: { guestOnly?: boolean }) {
  const location = useLocation();
  const {
    activeMakerspace,
    chooseMakerspace,
    login,
    makerspaces,
    queryClient,
    recovery,
    refreshAuthUser,
    restoring,
    routeMakerspace,
    routeMakerspaceSlug,
    selected,
    setTab,
    setUser,
    signOut,
    singleTenantLocked,
    socialLoginSucceeded,
    tenant,
    user,
  } = useStaffSession(guestOnly);
  if (restoring) {
    return <StaffLoading message="Restoring session..." restoring />;
  }

  if (!user) {
    return (
      <LoginPanel
        error={login.error?.message}
        guestOnly={guestOnly}
        isPending={login.isPending}
        onSubmit={login.mutate}
        onSocialSuccess={socialLoginSucceeded}
      />
    );
  }

  if (user.must_change_password) {
    return (
      <ChangePasswordGate
        username={user.username}
        onChanged={() => {
          // Clear the gate AND drop any error-cached protected queries so the
          // console opens with fresh data instead of a stale 403.
          queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
          setUser({ ...user, must_change_password: false });
        }}
        onSignOut={signOut}
      />
    );
  }

  const isSuperadmin = user.is_superuser || user.role === "superadmin";
  const globalOrganizationRoute = tabFromStaffPath(location.pathname, guestOnly) === "organizations";

  if (isSuperadmin && recovery.data?.mode === "quarantined") {
    return (
      <RecoveryQuarantinePanel
        state={recovery.data}
        onAcknowledged={(next) => {
          queryClient.setQueryData(["deployment-recovery-state"], next);
          queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
        }}
      />
    );
  }

  if (singleTenantLocked && makerspaces.isLoading) {
    return <StaffLoading message="Checking makerspace access..." />;
  }

  const hasSingleTenantAccess =
    !singleTenantLocked || Boolean(activeMakerspace);

  if (!hasSingleTenantAccess) {
    return (
      <StaffAccessDenied
        makerspaceName={tenant.bootstrap?.makerspace.name}
        onSignOut={signOut}
      />
    );
  }

  if (!singleTenantLocked && routeMakerspaceSlug && makerspaces.isLoading) {
    return <StaffLoading message="Opening makerspace..." />;
  }

  if (!singleTenantLocked && routeMakerspace && routeMakerspace.id !== selected) {
    return <StaffLoading message="Opening makerspace..." />;
  }

  if (!singleTenantLocked && selected !== null && makerspaces.isLoading) {
    return <StaffLoading message="Restoring makerspace..." />;
  }

  if (!singleTenantLocked && isSuperadmin && selected !== null && !activeMakerspace && !globalOrganizationRoute) {
    return (
      <MakerspacePicker
        makerspaces={makerspaces.data ?? []}
        loading={makerspaces.isLoading}
        username={user.username}
        onSelect={chooseMakerspace}
        onSignOut={signOut}
      />
    );
  }

  if (!singleTenantLocked && isSuperadmin && selected === null && !globalOrganizationRoute) {
    return (
      <MakerspacePicker
        makerspaces={makerspaces.data ?? []}
        loading={makerspaces.isLoading}
        username={user.username}
        onSelect={chooseMakerspace}
        onSignOut={signOut}
      />
    );
  }

  const activeMembership = user.makerspaces.find((item) => item.id === selected);
  const activeActions = activeMembership?.actions ?? [];
  const makerspaceList = makerspaces.data ?? [];

  return (
    <StaffWorkspace
      activeMakerspace={activeMakerspace}
      actions={activeActions}
      canConfigureMachineTypes={activeMembership?.can_configure_machine_types ?? isSuperadmin}
      isMachineOnly={activeMembership?.is_machine_only ?? false}
      guestOnly={guestOnly}
      isSuperadmin={isSuperadmin}
      makerspaces={makerspaceList}
      onAuthRefresh={refreshAuthUser}
      selected={selected}
      setSelected={chooseMakerspace}
      setTab={setTab}
      signOut={signOut}
      singleTenantLocked={singleTenantLocked}
      user={user}
    />
  );
}
