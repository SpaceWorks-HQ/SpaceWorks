import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";

import {
  addAuthExpiredListener,
  clearAccessToken,
  fetchMe,
  logout as logoutStaff,
  refreshAccessToken,
  setAccessToken,
  staffRequest,
  type PasswordLoginRequest,
  type PasswordLoginResponse,
  type StaffAuthUser,
} from "../../lib/api";
import type { SocialLoginResult } from "../auth/socialSdk";
import { type RecoveryState } from "./RecoveryQuarantinePanel";
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
import { wipeOfflineScopes } from "./eventCheckInOfflineStore";

export function useStaffSession(guestOnly: boolean) {
  const tenant = useTenant();
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const [user, setUser] = useState<StaffAuthUser | null>(null);
  const [selected, setSelectedState] = useState<number | null>(() => readStoredMakerspace());
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
    void wipeOfflineScopes("staff:");
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
      staffRequest<PasswordLoginResponse<StaffAuthUser>>("/auth/login", {
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ ...payload, surface: "staff" } satisfies PasswordLoginRequest),
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
  const recovery = useQuery({
    queryKey: ["deployment-recovery-state"],
    queryFn: () => staffRequest<RecoveryState>("/recovery"),
    enabled: Boolean(user && (user.is_superuser || user.role === "superadmin")),
    retry: false,
  });
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

  const signOut = async () => {
    await logoutStaff();
    await wipeOfflineScopes("staff:");
    setUser(null);
    setSelected(null);
    queryClient.clear();
  };

  return {
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
  };
}
