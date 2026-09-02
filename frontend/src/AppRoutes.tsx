import type { ReactNode } from "react";
import { Route, Routes, useLocation } from "react-router-dom";

import { AboutPage } from "./features/AboutPage";
import { PublicBookingsPage } from "./features/bookings/PublicBookingsPage";
import { PublicEventFeedbackPage } from "./features/inventory/PublicEventFeedbackPage";
import { PublicEventsPage } from "./features/inventory/PublicEventsPage";
import { PublicInventoryPage } from "./features/inventory/PublicInventoryPage";
import { PublicMachinesPage } from "./features/inventory/PublicMachinesPage";
import { PublicSelfCheckoutPage } from "./features/inventory/PublicSelfCheckoutPage";
import { ArchivedPayments } from "./features/members/ArchivedPayments";
import { MemberArea } from "./features/members/MemberArea";
import { PublicPrintRequestPage } from "./features/printing/PublicPrintRequestPage";
import { PublicOrganizationPage } from "./features/organizations/PublicOrganizationPage";
import { OrganizationInvitationRedeemPage } from "./features/organizations/OrganizationInvitationRedeemPage";
import { KioskPage, ScannerPage, SuperadminPage } from "./features/staff/PlatformApps";
import { ResetPasswordPage } from "./features/staff/ResetPasswordPage";
import { StaffApp } from "./features/staff/StaffApp";
import { EventCheckInStationPage } from "./features/events/EventCheckInStationPage";
import { PublicStatsPage } from "./features/stats/PublicStatsPage";

function NotFoundPage() {
  return <main className="grid min-h-screen place-items-center bg-bg px-6"><div className="text-center"><p className="eyebrow font-mono">404</p><h1 className="title-page mt-2">Page not found</h1></div></main>;
}

export function AppRoutes({ mode, landing }: { mode: "single" | "central"; landing: ReactNode }) {
  const location = useLocation();
  if (location.pathname === "/member/archived") {
    return <Routes><Route path="/member/archived" element={<ArchivedPayments />} /></Routes>;
  }
  if (location.pathname.startsWith("/organization-invitations/redeem/")) {
    return <Routes><Route path="/organization-invitations/redeem/:token" element={<OrganizationInvitationRedeemPage />} /></Routes>;
  }
  if (mode === "single") return <Routes>
    <Route path="/" element={<PublicInventoryPage />} />
    <Route path="/checkout" element={<PublicSelfCheckoutPage />} />
    <Route path="/events" element={<PublicEventsPage />} />
    <Route path="/events/:publicToken/feedback" element={<PublicEventFeedbackPage />} />
    <Route path="/event-check-in/:stationToken" element={<EventCheckInStationPage />} />
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
  </Routes>;
  return <Routes>
    <Route path="/" element={landing} />
    <Route path="/about" element={<AboutPage />} />
    <Route path="/o/:organizationSlug" element={<PublicOrganizationPage />} />
    <Route path="/m/:slug" element={<PublicInventoryPage />} />
    <Route path="/m/:slug/checkout" element={<PublicSelfCheckoutPage />} />
    <Route path="/m/:slug/events" element={<PublicEventsPage />} />
    <Route path="/m/:slug/events/:publicToken/feedback" element={<PublicEventFeedbackPage />} />
    <Route path="/m/:slug/event-check-in/:stationToken" element={<EventCheckInStationPage />} />
    <Route path="/m/:slug/machines" element={<PublicMachinesPage />} />
    <Route path="/m/:slug/bookings" element={<PublicBookingsPage />} />
    <Route path="/m/:slug/admin/*" element={<StaffApp />} />
    <Route path="/m/:slug/print" element={<PublicPrintRequestPage />} />
    <Route path="/m/:slug/member" element={<MemberArea />} />
    <Route path="/member" element={<MemberArea />} />
    <Route path="/m/:slug/stats" element={<PublicStatsPage />} />
    <Route path="/kiosk/:slug" element={<KioskPage />} />
    <Route path="/reset-password" element={<ResetPasswordPage />} />
    <Route path="/admin/*" element={<StaffApp />} />
    <Route path="/guest-admin/*" element={<StaffApp guestOnly />} />
    <Route path="/scanner" element={<ScannerPage />} />
    <Route path="/superadmin" element={<SuperadminPage />} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes>;
}
