import { lazy, Suspense, type ReactNode } from "react";
import { Route, Routes, useLocation, useParams } from "react-router-dom";

import { PublicInventoryPage } from "./features/inventory/PublicInventoryPage";
import { useTenantBootstrap } from "./features/inventory/usePublicInventory";
import { PublicDeskKioskPage } from "./features/kiosk/PublicDeskKioskPage";
import { ScannerPage } from "./features/kiosk/ScannerPage";
import { SuperadminPage } from "./features/staff/PlatformApps";
import { StaffApp } from "./features/staff/StaffApp";
import { useTenant } from "./lib/tenant";
import { publicHome } from "./lib/publicHome";

// Every public surface below is its own chunk. The catalogue and the staff shell stay eager
// because they are the two pages almost every visit lands on; everything else loads when its
// route is first visited, so a lending-only install never downloads events, bookings or
// machines code. The staff panels inside StaffApp are already lazy (StaffTabContent.tsx).
const AboutPage = lazy(() => import("./features/AboutPage").then((m) => ({ default: m.AboutPage })));
const PublicBookingsPage = lazy(() => import("./features/bookings/PublicBookingsPage").then((m) => ({ default: m.PublicBookingsPage })));
const PublicItemPage = lazy(() => import("./features/inventory/PublicItemPage").then((m) => ({ default: m.PublicItemPage })));
const PublicEventFeedbackPage = lazy(() => import("./features/inventory/PublicEventFeedbackPage").then((m) => ({ default: m.PublicEventFeedbackPage })));
const PublicEventDetailPage = lazy(() => import("./features/inventory/PublicEventDetailPage").then((m) => ({ default: m.PublicEventDetailPage })));
const PublicEventsPage = lazy(() => import("./features/inventory/PublicEventsPage").then((m) => ({ default: m.PublicEventsPage })));
const PublicMachinesPage = lazy(() => import("./features/inventory/PublicMachinesPage").then((m) => ({ default: m.PublicMachinesPage })));
const PublicSelfCheckoutPage = lazy(() => import("./features/inventory/PublicSelfCheckoutPage").then((m) => ({ default: m.PublicSelfCheckoutPage })));
const ArchivedPayments = lazy(() => import("./features/members/ArchivedPayments").then((m) => ({ default: m.ArchivedPayments })));
const MemberArea = lazy(() => import("./features/members/MemberArea").then((m) => ({ default: m.MemberArea })));
const MemberAccountPage = lazy(() => import("./features/members/MemberAccountPage").then((m) => ({ default: m.MemberAccountPage })));
const PublicPrintRequestPage = lazy(() => import("./features/printing/PublicPrintRequestPage").then((m) => ({ default: m.PublicPrintRequestPage })));
const PublicOrganizationPage = lazy(() => import("./features/organizations/PublicOrganizationPage").then((m) => ({ default: m.PublicOrganizationPage })));
const OrganizationInvitationRedeemPage = lazy(() => import("./features/organizations/OrganizationInvitationRedeemPage").then((m) => ({ default: m.OrganizationInvitationRedeemPage })));
const ResetPasswordPage = lazy(() => import("./features/staff/ResetPasswordPage").then((m) => ({ default: m.ResetPasswordPage })));
const EventCheckInStationPage = lazy(() => import("./features/events/EventCheckInStationPage").then((m) => ({ default: m.EventCheckInStationPage })));
const KioskStationPage = lazy(() => import("./features/kiosk/KioskStationPage").then((m) => ({ default: m.KioskStationPage })));
const PublicStatsPage = lazy(() => import("./features/stats/PublicStatsPage").then((m) => ({ default: m.PublicStatsPage })));

function NotFoundPage() {
  return <main className="grid min-h-screen place-items-center bg-bg px-6"><div className="text-center"><p className="eyebrow font-mono">404</p><h1 className="title-page mt-2">Page not found</h1></div></main>;
}

// Tenant capabilities choose the home independently of the deployment edition.
function FamilyHome() {
  const tenant = useTenant();
  const { slug = "" } = useParams();
  const bootstrapQuery = useTenantBootstrap(slug, tenant.mode === "central" && Boolean(slug));
  const bootstrap = tenant.mode === "single" ? tenant.bootstrap : bootstrapQuery.data;
  if (!bootstrap) {
    if (bootstrapQuery.error) return <main className="desk-shell p-8" role="alert">Unable to load this makerspace.</main>;
    return <RouteFallback />;
  }
  switch (publicHome(bootstrap)) {
    case "events": return <PublicEventsPage />;
    case "bookings": return <PublicBookingsPage />;
    case "machines": return <PublicMachinesPage />;
    case "membership": return <MemberArea />;
    case "inventory": return <PublicInventoryPage />;
    default: return <main className="desk-shell p-8"><h1 className="title-page">{bootstrap.branding.display_name || bootstrap.makerspace.name}</h1><p className="mt-3 text-muted">No public programme is available.</p></main>;
  }
}

const MfaAccountPage = lazy(() => import("./features/auth/MfaAccountPage").then((m) => ({ default: m.MfaAccountPage })));
const StaffInvitationAcceptPage = lazy(() => import("./features/auth/StaffInvitationAcceptPage").then((m) => ({ default: m.StaffInvitationAcceptPage })));

function RouteFallback() {
  return <main className="grid min-h-screen place-items-center bg-bg px-6"><p className="text-sm font-semibold text-muted">Loading...</p></main>;
}

export function AppRoutes({ mode, landing }: { mode: "single" | "central"; landing: ReactNode }) {
  const location = useLocation();
  let routes: ReactNode;
  if (location.pathname === "/mfa") {
    routes = <Routes><Route path="/mfa" element={<MfaAccountPage />} /></Routes>;
  } else if (location.pathname === "/staff-invitations/accept") {
    routes = <Routes><Route path="/staff-invitations/accept" element={<StaffInvitationAcceptPage />} /></Routes>;
  } else if (location.pathname === "/member/archived") {
    routes = <Routes><Route path="/member/archived" element={<ArchivedPayments />} /></Routes>;
  } else if (location.pathname.startsWith("/organization-invitations/redeem/")) {
    routes = <Routes><Route path="/organization-invitations/redeem/:token" element={<OrganizationInvitationRedeemPage />} /></Routes>;
  } else if (mode === "single") {
    routes = <Routes>
      <Route path="/" element={<FamilyHome />} />
      <Route path="/items/:itemId" element={<PublicItemPage />} />
      <Route path="/checkout" element={<PublicSelfCheckoutPage />} />
      <Route path="/events" element={<PublicEventsPage />} />
      <Route path="/events/:publicToken" element={<PublicEventDetailPage />} />
      <Route path="/events/:publicToken/feedback" element={<PublicEventFeedbackPage />} />
      <Route path="/event-check-in/:stationToken" element={<EventCheckInStationPage />} />
      <Route path="/machines" element={<PublicMachinesPage />} />
      <Route path="/bookings" element={<PublicBookingsPage />} />
      <Route path="/print" element={<PublicPrintRequestPage />} />
      <Route path="/member" element={<MemberArea />} />
      <Route path="/member/account" element={<MemberAccountPage />} />
      <Route path="/member/:memberTab" element={<MemberArea />} />
      <Route path="/stats" element={<PublicStatsPage />} />
      <Route path="/about" element={<AboutPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/admin/*" element={<StaffApp />} />
      <Route path="/guest-admin/*" element={<StaffApp guestOnly />} />
      <Route path="/scanner" element={<ScannerPage />} />
      <Route path="/kiosk/:stationToken" element={<KioskStationPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>;
  } else {
    routes = <Routes>
      <Route path="/" element={landing} />
      <Route path="/about" element={<AboutPage />} />
      <Route path="/o/:organizationSlug" element={<PublicOrganizationPage />} />
      <Route path="/m/:slug" element={<FamilyHome />} />
      <Route path="/m/:slug/items/:itemId" element={<PublicItemPage />} />
      <Route path="/m/:slug/checkout" element={<PublicSelfCheckoutPage />} />
      <Route path="/m/:slug/events" element={<PublicEventsPage />} />
      <Route path="/m/:slug/events/:publicToken" element={<PublicEventDetailPage />} />
      <Route path="/m/:slug/events/:publicToken/feedback" element={<PublicEventFeedbackPage />} />
      <Route path="/m/:slug/event-check-in/:stationToken" element={<EventCheckInStationPage />} />
      <Route path="/m/:slug/machines" element={<PublicMachinesPage />} />
      <Route path="/m/:slug/bookings" element={<PublicBookingsPage />} />
      <Route path="/m/:slug/admin/*" element={<StaffApp />} />
      <Route path="/m/:slug/print" element={<PublicPrintRequestPage />} />
      <Route path="/m/:slug/member" element={<MemberArea />} />
      <Route path="/m/:slug/member/account" element={<MemberAccountPage />} />
      <Route path="/member" element={<MemberArea />} />
      <Route path="/member/account" element={<MemberAccountPage />} />
      <Route path="/m/:slug/member/:memberTab" element={<MemberArea />} />
      <Route path="/member/:memberTab" element={<MemberArea />} />
      <Route path="/m/:slug/stats" element={<PublicStatsPage />} />
      <Route path="/m/:slug/kiosk/:stationToken" element={<KioskStationPage />} />
      <Route path="/kiosk/:slug" element={<PublicDeskKioskPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/admin/*" element={<StaffApp />} />
      <Route path="/guest-admin/*" element={<StaffApp guestOnly />} />
      <Route path="/scanner" element={<ScannerPage />} />
      <Route path="/superadmin" element={<SuperadminPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>;
  }
  return <Suspense fallback={<RouteFallback />}>{routes}</Suspense>;
}
