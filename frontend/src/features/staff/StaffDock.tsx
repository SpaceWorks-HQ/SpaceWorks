import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useLocation } from "react-router-dom";

import type { Makerspace } from "./panels/shared";
import { StaffDockPopover, staffDockPopoverId, type DockFocusEdge } from "./StaffDockPopover";
import { STAFF_NAV_ICONS, StaffNavFallbackIcon } from "./staffNavIcons";
import { TAB_GROUPS } from "./staffAccess";
import { useDockAnchor } from "./useDockAnchor";
import { useUnreadNotifications } from "./useUnreadNotifications";

type StaffDockProps = {
  activeMakerspace?: Makerspace;
  activeTab: string;
  allowedTabs: readonly string[];
  guestOnly: boolean;
  setTab: (tab: string) => void;
  singleTenantLocked: boolean;
};

function badgeLabel(count: number) {
  return count > 99 ? "99+" : count;
}

// The four-colour language, carried over from the sidebar this dock replaced: `accent` (sky),
// `secondary` (pink), `success` (green), `warn` (yellow), cycled across the eight groups so a
// section is recognisable by colour as well as by name.
const GROUP_TONE_CLASSES: Record<string, string> = {
  Operate: "border-accent/40 text-accent-ink hover:bg-accent/15",
  Inventory: "border-secondary/40 text-secondary-ink hover:bg-secondary/15",
  Machines: "border-success/40 text-success-ink hover:bg-success/15",
  Events: "border-warn/40 text-warn-ink hover:bg-warn/15",
  Bookings: "border-accent/40 text-accent-ink hover:bg-accent/15",
  Members: "border-secondary/40 text-secondary-ink hover:bg-secondary/15",
  Insights: "border-success/40 text-success-ink hover:bg-success/15",
  Admin: "border-warn/40 text-warn-ink hover:bg-warn/15",
};

export function StaffDock({
  activeMakerspace,
  activeTab,
  allowedTabs,
  guestOnly,
  setTab,
  singleTenantLocked,
}: StaffDockProps) {
  const location = useLocation();
  const routeLocation = `${location.pathname}${location.search}${location.hash}`;
  const rootRef = useRef<HTMLElement | null>(null);
  const buttonRefs = useRef(new Map<string, HTMLButtonElement>());
  const previousRouteLocation = useRef(routeLocation);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [focusEdge, setFocusEdge] = useState<DockFocusEdge>(null);
  const [rovingGroup, setRovingGroup] = useState<string | null>(null);

  const visibleGroups = useMemo(
    () => TAB_GROUPS
      .map((group) => ({
        ...group,
        tabs: group.tabs.filter((tab) => allowedTabs.includes(tab)),
      }))
      .filter((group) => group.tabs.length > 0),
    [allowedTabs],
  );
  const activeGroup = visibleGroups.find((group) => group.tabs.includes(activeTab));
  const tabStopGroup = visibleGroups.some((group) => group.label === rovingGroup)
    ? rovingGroup
    : activeGroup?.label ?? visibleGroups[0]?.label ?? null;
  const openAnchor = openGroup ? buttonRefs.current.get(openGroup) ?? null : null;
  const popoverPosition = useDockAnchor(openAnchor, openGroup !== null);
  const unreadCount = useUnreadNotifications(
    activeMakerspace?.id,
    Boolean(activeMakerspace?.id) && allowedTabs.includes("notifications"),
  );

  useEffect(() => {
    const routeChanged = previousRouteLocation.current !== routeLocation;
    previousRouteLocation.current = routeLocation;
    if (!routeChanged || openGroup === null) return undefined;

    setOpenGroup(null);
    setFocusEdge(null);
    setRovingGroup(activeGroup?.label ?? null);
    window.requestAnimationFrame(() => {
      const activeButton = activeGroup ? buttonRefs.current.get(activeGroup.label) : null;
      (activeButton ?? document.getElementById("main-content"))?.focus();
    });
    return undefined;
  }, [activeGroup, openGroup, routeLocation]);

  useEffect(() => {
    if (openGroup && !visibleGroups.some((group) => group.label === openGroup)) {
      setOpenGroup(null);
      setFocusEdge(null);
    }
  }, [openGroup, visibleGroups]);

  useEffect(() => {
    if (openGroup === null) return undefined;
    const handleOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) {
        setOpenGroup(null);
        setFocusEdge(null);
      }
    };
    document.addEventListener("pointerdown", handleOutsidePointer);
    return () => document.removeEventListener("pointerdown", handleOutsidePointer);
  }, [openGroup]);

  const closePopover = (restoreFocus: boolean) => {
    const owner = openGroup ? buttonRefs.current.get(openGroup) : null;
    setOpenGroup(null);
    setFocusEdge(null);
    if (restoreFocus) window.requestAnimationFrame(() => owner?.focus());
  };

  const openPopover = (label: string, edge: Exclude<DockFocusEdge, null> | null) => {
    setRovingGroup(label);
    setOpenGroup(label);
    setFocusEdge(edge);
  };

  const moveButtonFocus = (index: number, direction: 1 | -1) => {
    const nextIndex = (index + direction + visibleGroups.length) % visibleGroups.length;
    const nextGroup = visibleGroups[nextIndex];
    setRovingGroup(nextGroup.label);
    buttonRefs.current.get(nextGroup.label)?.focus();
  };

  const handleButtonKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
    label: string,
  ) => {
    if (event.key === "Escape" && openGroup === label) {
      event.preventDefault();
      closePopover(true);
      return;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      if (openGroup !== null) closePopover(false);
      moveButtonFocus(index, event.key === "ArrowRight" ? 1 : -1);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      openPopover(label, event.key === "ArrowDown" ? "first" : "last");
    }
  };

  return (
    <nav
      ref={rootRef}
      data-staff-dock-root
      aria-label="Staff sections"
      className="material-chrome fixed inset-x-0 bottom-3 z-40 mx-auto w-fit max-w-[calc(100vw-1rem)] rounded-2xl border border-line shadow-soft-lg pb-[env(safe-area-inset-bottom)]"
    >
      <div
        data-staff-dock-scroller
        className="flex max-w-[calc(100vw-1rem)] snap-x snap-mandatory gap-1 overflow-x-auto p-2 sm:snap-none"
      >
        {visibleGroups.map((group, index) => {
          const active = group.label === activeGroup?.label;
          const open = group.label === openGroup;
          const ownsNotifications = group.tabs.includes("notifications");
          const Icon = STAFF_NAV_ICONS[group.label] ?? StaffNavFallbackIcon;
          const accessibleLabel = ownsNotifications && unreadCount > 0
            ? `${group.label}, ${unreadCount} unread`
            : group.label;
          return (
            <button
              key={group.label}
              ref={(element) => {
                if (element) buttonRefs.current.set(group.label, element);
                else buttonRefs.current.delete(group.label);
              }}
              type="button"
              // With the label permanently visible, an aria-label that merely repeats it is noise.
              // Keep one ONLY to fold in the unread count, and keep the visible text as its prefix
              // so the accessible name still contains what a sighted user reads.
              aria-label={ownsNotifications && unreadCount > 0 ? accessibleLabel : undefined}
              // The row carrying aria-current="page" is unmounted while the popover is closed, so
              // without this the current section is conveyed by colour alone -- a regression against
              // the sidebar, where the active tab was always exposed.
              aria-current={active ? "true" : undefined}
              aria-expanded={open}
              aria-controls={staffDockPopoverId(group.label)}
              className={`desk-button-ghost relative min-h-11 shrink-0 snap-center gap-2 px-3 ${
                active ? "desk-nav-item-active" : GROUP_TONE_CLASSES[group.label] ?? GROUP_TONE_CLASSES.Operate
              }`}
              tabIndex={tabStopGroup === group.label ? 0 : -1}
              onClick={() => {
                setRovingGroup(group.label);
                if (open) closePopover(false);
                else openPopover(group.label, null);
              }}
              onFocus={() => setRovingGroup(group.label)}
              onKeyDown={(event) => handleButtonKeyDown(event, index, group.label)}
            >
              <Icon className="shrink-0" />
              {/* Clash Display, title case. The sidebar deliberately made these <h2> so the base
                  layer handed them the display face, reasoning that the display voice is what makes
                  a group read as a TOPIC rather than as a mono `.eyebrow` label. A tab bar is not a
                  heading list, so the face is applied directly instead of borrowing <h2> semantics. */}
              <span className="whitespace-nowrap font-display text-sm font-medium leading-none">
                {group.label}
              </span>
              {ownsNotifications && unreadCount > 0 ? (
                <span className="absolute -right-1 -top-1 min-w-5 rounded-full bg-danger px-1 font-mono text-[10px] font-semibold leading-5 text-bg" aria-hidden>
                  {badgeLabel(unreadCount)}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {visibleGroups.map((group) => (
        <StaffDockPopover
          key={group.label}
          activeMakerspace={activeMakerspace}
          activeTab={activeTab}
          focusEdge={group.label === openGroup ? focusEdge : null}
          group={group}
          guestOnly={guestOnly}
          open={group.label === openGroup}
          ownerButton={buttonRefs.current.get(group.label) ?? null}
          position={popoverPosition}
          singleTenantLocked={singleTenantLocked}
          tabs={group.tabs}
          unreadCount={unreadCount}
          onClose={closePopover}
          onFocusSettled={() => setFocusEdge(null)}
          onSelect={setTab}
        />
      ))}
    </nav>
  );
}
