import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { staffRequest } from "../../lib/api";
import type { Makerspace } from "./panels/shared";
import { TAB_GROUPS, TAB_LABELS } from "./staffAccess";
import { staffTabPath } from "./staffTabs";

function NotificationUnreadBadge({ makerspaceId }: { makerspaceId: number }) {
  const query = useQuery({
    queryKey: ["notifications-unread", makerspaceId],
    queryFn: () => staffRequest<{ count: number }>(`/notifications/makerspace/${makerspaceId}/unread-count`),
    refetchInterval: 60_000,
    retry: false,
  });
  const count = query.data?.count ?? 0;
  if (query.isError || count <= 0) return null;
  return (
    <span className="ml-auto shrink-0 rounded-full bg-danger px-1.5 text-xs font-semibold text-bg">
      {count > 99 ? "99+" : count}
    </span>
  );
}

export function StaffSidebar({
  activeMakerspace,
  activeTab,
  allowedTabs,
  collapsedGroups,
  guestOnly,
  isSuperadmin,
  makerspaces,
  printingOnly,
  selected,
  setSelected,
  setTab,
  singleTenantLocked,
  toggleGroup,
}: {
  activeMakerspace?: Makerspace;
  activeTab: string;
  allowedTabs: readonly string[];
  collapsedGroups: Set<string>;
  guestOnly: boolean;
  isSuperadmin: boolean;
  makerspaces: Makerspace[];
  printingOnly: boolean;
  selected: number | null;
  setSelected: (id: number) => void;
  setTab: (tab: string) => void;
  singleTenantLocked: boolean;
  toggleGroup: (label: string) => void;
}) {
  return (
    <aside className="min-w-0 border-b border-line bg-panel lg:min-h-screen lg:border-b-0 lg:border-r">
      <div className="flex min-w-0 items-center gap-3 border-b border-line px-5 py-4">
        <SpaceWorksBadge className="shrink-0" />
        <div className="min-w-0">
          <p className="truncate font-mono text-xs uppercase text-muted">
            {guestOnly ? "Guest admin" : isSuperadmin ? "Super Admin" : printingOnly ? "Print Manager" : "Space Manager"}
          </p>
        </div>
      </div>
      <div className="p-4">
        {singleTenantLocked ? (
          <div className="break-words rounded-lg border border-line bg-accent px-3 py-2 text-sm font-semibold text-on-accent dark:bg-[#0b2a38] dark:text-[#7dd3fc]">
            {activeMakerspace?.name ?? "Configured makerspace"}
          </div>
        ) : (
          <select
            className="desk-input w-full"
            // The visible context is the option text itself, so there is no visible
            // label to point at; without this the control is announced as just
            // "combobox" with no indication of what it switches.
            aria-label="Active makerspace"
            value={selected ?? ""}
            onChange={(event) => setSelected(Number(event.target.value))}
          >
            {makerspaces.map((makerspace) => (
              <option key={makerspace.id} value={makerspace.id}>
                {makerspace.name}
              </option>
            ))}
          </select>
        )}
        {/* Named landmark: a staff page carries more than one nav region, and
            "navigation" repeated twice tells a screen-reader user nothing. */}
        <nav className="mt-4 space-y-3" aria-label="Staff sections">
          {TAB_GROUPS.map((group) => {
            const tabs = group.tabs.filter((tab) => allowedTabs.includes(tab));
            if (tabs.length === 0) return null;
            const open = !collapsedGroups.has(group.label) || tabs.includes(activeTab);
            const groupId = `staff-nav-group-${group.label.replace(/\W+/g, "-").toLowerCase()}`;
            return (
              <div key={group.label}>
                <button
                  className="flex min-h-11 w-full items-center justify-between border-b border-line px-1 pb-1 font-display text-sm font-bold tracking-tight text-ink transition hover:text-accent-ink"
                  type="button"
                  aria-expanded={open}
                  aria-controls={groupId}
                  onClick={() => toggleGroup(group.label)}
                >
                  <span className="min-w-0 truncate">{group.label}</span>
                  <span aria-hidden>{open ? "-" : "+"}</span>
                </button>
                {open ? (
                  <div className="mt-1 grid gap-1" id={groupId}>
                    {tabs.map((item) => (
                      <Link
                        key={item}
                        aria-current={activeTab === item ? "page" : undefined}
                        className={`desk-nav-item ${activeTab === item ? "desk-nav-item-active" : ""}`}
                        to={staffTabPath(item, guestOnly, activeMakerspace?.slug, singleTenantLocked)}
                        onClick={() => setTab(item)}
                      >
                        <span className="min-w-0 truncate">{TAB_LABELS[item] ?? item}</span>
                        {item === "notifications" && activeMakerspace ? (
                          <NotificationUnreadBadge makerspaceId={activeMakerspace.id} />
                        ) : null}
                      </Link>
                    ))}
                  </div>
                ) : <div id={groupId} hidden />}
              </div>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}
