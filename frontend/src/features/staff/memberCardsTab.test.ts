import { describe, expect, it } from "vitest";

import { getStaffAccess, TAB_GROUPS, TAB_LABELS } from "./staffAccess";
import { filterTabsByEnabledModules, staffTabPath, tabFromStaffPath } from "./staffTabs";

// A sibling file rather than more lines in staffTabs.test.ts, which is already past the
// 300-line ceiling in CLAUDE.md and must be split in its own commit before it grows.
describe("member cards tab", () => {
  it("routes to /member-cards and sits beside Members", () => {
    expect(staffTabPath("cards", false)).toBe("/admin/member-cards");
    expect(staffTabPath("cards", false, "forge")).toBe("/m/forge/admin/member-cards");
    expect(tabFromStaffPath("/admin/member-cards", false)).toBe("cards");
    expect(TAB_LABELS.cards).toBe("Member cards");
    expect(TAB_GROUPS.find((group) => group.label === "Members")?.tabs).toEqual([
      "members",
      "cards",
    ]);
  });

  it("needs a member-card action and the membership module", () => {
    const allowed = getStaffAccess(["manage_member_cards"], false, false).allowedTabs;
    expect(allowed).toContain("cards");
    // A front-desk role holding only the scan action still needs the lookup.
    expect(getStaffAccess(["scan_member_cards"], false, false).allowedTabs).toContain("cards");
    // MANAGE_MAKERSPACE is NOT the backend gate, so it does not open this tab on its own.
    expect(getStaffAccess(["manage_makerspace"], false, false).allowedTabs).not.toContain("cards");
    expect(getStaffAccess(["edit_inventory"], false, false).allowedTabs).not.toContain("cards");
    // A card hangs off a membership, so without that module every endpoint 404s.
    expect(filterTabsByEnabledModules(allowed, { enabled_modules: ["staff_admin"] })).not.toContain(
      "cards",
    );
    expect(
      filterTabsByEnabledModules(allowed, { enabled_modules: ["staff_admin", "membership"] }),
    ).toContain("cards");
  });
});
