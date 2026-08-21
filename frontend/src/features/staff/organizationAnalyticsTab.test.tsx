import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { StaffAuthUser } from "../../lib/api";
import { StaffTabContent } from "./StaffTabContent";
import { getStaffAccess, TAB_GROUPS, TAB_LABELS } from "./staffAccess";
import { staffTabPath, tabFromStaffPath } from "./staffTabs";

const makerspace = {
  id: 19,
  name: "North workshop",
  public_code: "NORTH",
  slug: "north",
  telegram_group_chat_id: "",
  frontend_domain: null,
  hidden_from_central_directory: false,
};

const user: StaffAuthUser = {
  username: "owner",
  email_verified: true,
  role: "staff",
  is_superuser: false,
  must_change_password: false,
  makerspaces: [],
};

describe("organization analytics tab", () => {
  it("is registered with a stable route and Insights label", () => {
    expect(TAB_LABELS["organization-analytics"]).toBe("Organization analytics");
    expect(TAB_GROUPS.find((group) => group.label === "Insights")?.tabs)
      .toContain("organization-analytics");
    expect(staffTabPath("organization-analytics", false)).toBe("/admin/organization-analytics");
    expect(tabFromStaffPath("/admin/organization-analytics", false))
      .toBe("organization-analytics");
  });

  it("does not advertise or mount the targetless panel when single-tenant locked", () => {
    expect(getStaffAccess(["view_audit"], false, true).allowedTabs)
      .not.toContain("organization-analytics");

    render(
      <StaffTabContent
        activeMakerspace={makerspace}
        activeTab="organization-analytics"
        guestOnly={false}
        makerspaces={[makerspace]}
        isSuperadmin={false}
        currentUser={user}
        onAuthRefresh={() => {}}
        printingOnly={false}
        canChooseToBuyKind={false}
        canEditInventory={false}
        canIssueDirectLoan={false}
        canCollectServiceRequests={false}
        canUseToBuy={false}
        canManageQr={false}
        canManageMakerspace={false}
        canManageMachines={false}
        isMachineOnly={false}
        canConfigureMachineTypes={false}
        canManageEvents={false}
        canManageBookings={false}
        canSeeHardware={false}
        canSeePrinting={false}
        canViewAudit
        singleTenantLocked
      />,
    );

    expect(screen.queryByRole("heading", { name: "Organization analytics" }))
      .not.toBeInTheDocument();
  });
});
