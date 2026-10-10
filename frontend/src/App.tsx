import { AppRoutes } from "./AppRoutes";
import { lazy, Suspense } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { SpaceWorksBadge } from "./components/SpaceWorksLogo";
import { LandingPage } from "./features/LandingPage";
import { useTenant } from "./lib/tenant";

const KioskStationPage = lazy(() => import("./features/kiosk/KioskStationPage").then((m) => ({ default: m.KioskStationPage })));

export default function App() {
  const tenant = useTenant();
  const { pathname } = useLocation();
  // Station UUID routes must open their precached shell even when no-store
  // config.js / tenant bootstrap cannot load. Central /kiosk/:slug stays distinct.
  if (/^\/m\/[^/]+\/kiosk\/[^/]+\/?$/.test(pathname)
      || /^\/kiosk\/[0-9a-f-]{36}\/?$/i.test(pathname)) {
    return <Suspense fallback={<main className="desk-shell p-5">Loading kiosk…</main>}><Routes>
      <Route path="/kiosk/:stationToken" element={<KioskStationPage />} />
      <Route path="/m/:slug/kiosk/:stationToken" element={<KioskStationPage />} />
    </Routes></Suspense>;
  }
  // Do not gate this payment-only recovery route on archived tenant bootstrap: the tenant
  // screens below ("Loading site", "Site unavailable") are exactly what an archived member
  // must get past. Read the ROUTER's location, not `window.location` -- a client-side `Link`
  // updates router context without touching `window.location`, so a non-reactive read left
  // this branch stale and sent every click on the recovery CTA to the not-found page.
  if (tenant.mode === "single" && tenant.loading) {
    return (
      <main className="desk-shell grid place-items-center px-5">
        <div className="desk-panel w-full max-w-md p-6 text-sm font-semibold text-muted">
          <SpaceWorksBadge className="mb-5" />
          Loading site...
        </div>
      </main>
    );
  }

  if (tenant.mode === "single" && tenant.error) {
    return (
      <main className="desk-shell grid place-items-center px-5">
        <div className="desk-panel w-full max-w-md p-6">
          <SpaceWorksBadge className="mb-5" />
          <h1 className="title-page">Site unavailable</h1>
          <p className="mt-2 text-sm text-muted">
            The configured tenant could not be resolved.
          </p>
        </div>
      </main>
    );
  }

  return <AppRoutes mode={tenant.mode} landing={<LandingPage />} />;
}
