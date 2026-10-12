import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { kioskScope, memberScope } from "../lib/pwaScopes";

export function PwaRegistration() {
  const { pathname } = useLocation();
  useEffect(() => {
    if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
    void (async () => {
      // Retire the historical root registration, preserving its queued data.
      for (const registration of await navigator.serviceWorker.getRegistrations()) {
        if (new URL(registration.scope).pathname === "/") await registration.unregister();
      }
      const member = memberScope(pathname);
      const kiosk = kioskScope(pathname);
      if (member || kiosk) await navigator.serviceWorker.register(member ? "/member-sw.js" : "/sw.js", {
        scope: member ?? kiosk!, updateViaCache: "none",
      });
    })().catch(() => undefined);
  }, [pathname]);
  return null;
}
