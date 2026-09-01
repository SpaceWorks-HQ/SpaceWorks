import { Route, Routes, useLocation } from "react-router-dom";

import { SpaceWorksBadge } from "./components/SpaceWorksLogo";
import { AboutPage } from "./features/AboutPage";
import { LandingPage } from "./features/LandingPage";
import { PublicBookingsPage } from "./features/bookings/PublicBookingsPage";
import { PublicInventoryPage } from "./features/inventory/PublicInventoryPage";
import { PublicEventsPage } from "./features/inventory/PublicEventsPage";
import { PublicMachinesPage } from "./features/inventory/PublicMachinesPage";
import { PublicSelfCheckoutPage } from "./features/inventory/PublicSelfCheckoutPage";
import { PublicOrganizationPage } from "./features/organizations/PublicOrganizationPage";
import { OrganizationInvitationRedeemPage } from "./features/organizations/OrganizationInvitationRedeemPage";
import { PublicPrintRequestPage } from "./features/printing/PublicPrintRequestPage";
import { ArchivedPayments } from "./features/members/ArchivedPayments";
import { MemberArea } from "./features/members/MemberArea";
import { KioskPage, ScannerPage, SuperadminPage } from "./features/staff/PlatformApps";
import { ResetPasswordPage } from "./features/staff/ResetPasswordPage";
import { StaffApp } from "./features/staff/StaffApp";
import { PublicStatsPage } from "./features/stats/PublicStatsPage";
import { useTenant } from "./lib/tenant";
function NotFoundPage() {
  return (
    <main className="grid min-h-screen place-items-center bg-bg px-6">
      <div className="text-center">
        <p className="eyebrow font-mono">
          404
        </p>
        <h1 className="title-page mt-2">Page not found</h1>
      </div>
    </main>
  );
}

export default function App() {
  const tenant = useTenant();
  // Do not gate this payment-only recovery route on archived tenant bootstrap: the tenant
  // screens below ("Loading site", "Site unavailable") are exactly what an archived member
  // must get past. Read the ROUTER's location, not `window.location` -- a client-side `Link`
  // updates router context without touching `window.location`, so a non-reactive read left
  // this branch stale and sent every click on the recovery CTA to the not-found page.
  const location = useLocation();
  if (location.pathname === "/member/archived") return <Routes><Route path="/member/archived" element={<ArchivedPayments />} /></Routes>;
  if (location.pathname.startsWith("/organization-invitations/redeem/")) {
    return <Routes><Route path="/organization-invitations/redeem/:token" element={<OrganizationInvitationRedeemPage />} /></Routes>;
  }

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

  if (tenant.mode === "single") {
    return (
      <Routes>
        <Route path="/" element={<PublicInventoryPage />} />
        <Route path="/checkout" element={<PublicSelfCheckoutPage />} />
        <Route path="/events" element={<PublicEventsPage />} />
        <Route path="/machines" element={<PublicMachinesPage />} />
        <Route path="/bookings" element={<PublicBookingsPage />} />
        <Route path="/print" element={<PublicPrintRequestPage />} />
        <Route path="/member" element={<MemberArea />} />
        <Route path="/stats" element={<PublicStatsPage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/admin/*" element={<StaffApp />} />
        <Route path="/guest-admin/*" element={<StaffApp guestOnly />} />
        <Route path="/scanner" element={<ScannerPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/about" element={<AboutPage />} />
      <Route path="/o/:organizationSlug" element={<PublicOrganizationPage />} />
      <Route path="/m/:slug" element={<PublicInventoryPage />} />
      <Route path="/m/:slug/checkout" element={<PublicSelfCheckoutPage />} />
      <Route path="/m/:slug/events" element={<PublicEventsPage />} />
      <Route path="/m/:slug/machines" element={<PublicMachinesPage />} />
      <Route path="/m/:slug/bookings" element={<PublicBookingsPage />} />
      <Route path="/m/:slug/admin/*" element={<StaffApp />} />
      <Route path="/m/:slug/print" element={<PublicPrintRequestPage />} />
      <Route path="/m/:slug/member" element={<MemberArea />} />
      {/* The central member entry point. Without it `/member` 404s on a central deployment,
          so a member whose only makerspace is ARCHIVED has nowhere to land: their tenant URL
          no longer resolves and `/m/:slug/member` needs a slug they can no longer discover.
          Tenant bootstrap fails here by design; MemberArea renders its recovery link anyway. */}
      <Route path="/member" element={<MemberArea />} />
      <Route path="/m/:slug/stats" element={<PublicStatsPage />} />
      <Route path="/kiosk/:slug" element={<KioskPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/admin/*" element={<StaffApp />} />
      <Route path="/guest-admin/*" element={<StaffApp guestOnly />} />
      <Route path="/scanner" element={<ScannerPage />} />
      <Route path="/superadmin" element={<SuperadminPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
