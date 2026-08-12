import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";

import {
  addAuthExpiredListener,
  clearAccessToken,
  fetchMe,
  logout as logoutStaff,
  refreshAccessToken,
  setAccessToken,
  staffRequest,
  type StaffAuthUser,
} from "../../lib/api";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ChangePasswordGate } from "./ChangePasswordGate";
import { LoginPanel } from "./LoginPanel";
import type { SocialLoginResult } from "../auth/socialSdk";
import { MakerspacePicker } from "./MakerspacePicker";
import { StaffAccessDenied } from "./StaffAccessDenied";
import { StaffWorkspace } from "./StaffWorkspace";
import {
  persistSelectedMakerspace,
  persistStaffTab,
  readStoredMakerspace,
  staffBasePath,
  staffMakerspaceSlugFromPath,
  staffTabPath,
  tabFromStaffPath,
} from "./staffTabs";
import { type Makerspace, useStaffGet } from "./panels/shared";
import { useTenant } from "../../lib/tenant";

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
  const tenant = useTenant();
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const [user, setUser] = useState<StaffAuthUser | null>(null);
  const [selected, setSelectedState] = useState<number | null>(() => readStoredMakerspace());
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
    () => new Set(["Admin"]),
  );
  const [restoring, setRestoring] = useState(true);
  const routeMakerspaceSlug = staffMakerspaceSlugFromPath(location.pathname, guestOnly);
  const routeMakerspaceSlugRef = useRef(routeMakerspaceSlug);
  const singleTenantLocked = tenant.mode === "single" && tenant.makerspaceId !== null;
  const setSelected = useCallback((value: number | null) => {
    setSelectedState(value);
    persistSelectedMakerspace(value);
  }, []);
  const setTab = useCallback((value: string) => {
    persistStaffTab(value);
  }, []);

  useEffect(() => {
    routeMakerspaceSlugRef.current = routeMakerspaceSlug;
  }, [routeMakerspaceSlug]);
  const hydrateUser = useCallback((nextUser: StaffAuthUser) => {
    setUser(nextUser);
    if (tenant.mode === "single" && tenant.makerspaceId !== null) {
      setSelected(tenant.makerspaceId);
      return;
    }
    const superadmin = nextUser.is_superuser || nextUser.role === "superadmin";
    const routeMembership = nextUser.makerspaces.find((item) => item.slug === routeMakerspaceSlugRef.current);
    if (routeMembership) {
      setSelected(routeMembership.id);
      return;
    }
    const saved = readStoredMakerspace();
    const staffSaved = nextUser.makerspaces.some((item) => item.id === saved) ? saved : null;
    setSelected(superadmin ? saved : staffSaved ?? nextUser.makerspaces[0]?.id ?? null);
  }, [setSelected, tenant.makerspaceId, tenant.mode]);

  // Refetch /auth/me and re-hydrate after a role edit/assignment may have changed the
  // current actor's own effective actions, so tabs/capabilities recompute immediately.
  const refreshAuthUser = useCallback(() => {
    fetchMe().then(hydrateUser).catch(() => {});
  }, [hydrateUser]);

  const expireSession = useCallback(() => {
    setUser(null);
    setSelected(null);
    setTab("");
    queryClient.clear();
  }, [queryClient, setSelected, setTab]);

  useEffect(() => addAuthExpiredListener(expireSession), [expireSession]);

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        try {
          const currentUser = await fetchMe();
          if (active) {
            hydrateUser(currentUser);
          }
        } catch {
          clearAccessToken();
          if (active) {
            setUser(null);
          }
        }
      }
      if (active) {
        setRestoring(false);
      }
    }

    restoreSession();
    return () => {
      active = false;
    };
  }, [hydrateUser]);

  const login = useMutation({
    mutationFn: (payload: { username: string; password: string }) =>
      staffRequest<{ access: string; user: StaffAuthUser }>("/auth/login", {
        method: "POST",
        credentials: "include",
        body: JSON.stringify(payload),
      }),
    onSuccess: (data) => {
      setAccessToken(data.access);
      hydrateUser(data.user);
    },
  });
  const socialLoginSucceeded = useCallback((result: SocialLoginResult) => {
    setAccessToken(result.access);
    hydrateUser(result.user as unknown as StaffAuthUser);
  }, [hydrateUser]);

  const makerspaces = useStaffGet<Makerspace[]>(
    ["staff", "makerspaces"],
    "/admin/makerspaces",
    Boolean(user) && !user?.must_change_password,
  );
  const chooseMakerspace = useCallback((id: number | null) => {
    if (singleTenantLocked) return;
    if (id === null) {
      setSelected(null);
      navigate(staffBasePath(guestOnly));
      return;
    }
    const ms = makerspaces.data?.find((m) => m.id === id);
    setSelected(id);
    // Only the non-guest staff console uses slug-scoped /m/<slug>/admin routes.
    // Guest-admin keeps its own shell, so leave its switching as-is (a slug
    // navigate here would remount the non-guest app and drop the guest UI).
    if (ms?.slug && !guestOnly) {
      const currentTab = tabFromStaffPath(location.pathname, guestOnly);
      navigate(staffTabPath(currentTab, guestOnly, ms.slug));
    }
  }, [guestOnly, location.pathname, makerspaces.data, navigate, setSelected, singleTenantLocked]);
  const activeMakerspace = useMemo(
    () => {
      return makerspaces.data?.find((item) => item.id === selected);
    },
    [makerspaces.data, selected],
  );

  const routeMakerspace = useMemo(() => {
    if (!routeMakerspaceSlug || !makerspaces.data) {
      return undefined;
    }
    return makerspaces.data.find((item) => item.slug === routeMakerspaceSlug);
  }, [makerspaces.data, routeMakerspaceSlug]);

  useEffect(() => {
    if (singleTenantLocked || !routeMakerspace || routeMakerspace.id === selected) {
      return;
    }
    setSelected(routeMakerspace.id);
  }, [routeMakerspace, selected, setSelected, singleTenantLocked]);

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
        onSignOut={async () => {
          await logoutStaff();
          setUser(null);
          setSelected(null);
          queryClient.clear();
        }}
      />
    );
  }

  const isSuperadmin = user.is_superuser || user.role === "superadmin";

  const signOut = async () => {
    await logoutStaff();
    setUser(null);
    setSelected(null);
    queryClient.clear();
  };

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

  if (!singleTenantLocked && isSuperadmin && selected !== null && !activeMakerspace) {
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

  if (!singleTenantLocked && isSuperadmin && selected === null) {
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

  const toggleGroup = (label: string) =>
    setCollapsedGroups((current) => {
      const next = new Set(current);
      if (next.has(label)) {
        next.delete(label);
      } else {
        next.add(label);
      }
      return next;
    });
  const activeMembership = user.makerspaces.find((item) => item.id === selected);
  const activeActions = activeMembership?.actions ?? [];
  const makerspaceList = makerspaces.data ?? [];

  return (
    <StaffWorkspace
      activeMakerspace={activeMakerspace}
      actions={activeActions}
      canConfigureMachineTypes={activeMembership?.can_configure_machine_types ?? isSuperadmin}
      isMachineOnly={activeMembership?.is_machine_only ?? false}
      collapsedGroups={collapsedGroups}
      guestOnly={guestOnly}
      isSuperadmin={isSuperadmin}
      makerspaces={makerspaceList}
      onAuthRefresh={refreshAuthUser}
      selected={selected}
      setSelected={chooseMakerspace}
      setTab={setTab}
      signOut={signOut}
      singleTenantLocked={singleTenantLocked}
      toggleGroup={toggleGroup}
      user={user}
    />
  );
}
