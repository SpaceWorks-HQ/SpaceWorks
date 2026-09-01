import { useEffect, useRef, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";

import type { Makerspace } from "./panels/shared";
import { TAB_LABELS, TAB_GROUPS } from "./staffAccess";
import { staffTabPath } from "./staffTabs";
import type { DockPopoverPosition } from "./useDockAnchor";

type StaffTabGroup = (typeof TAB_GROUPS)[number];
export type DockFocusEdge = "first" | "last" | null;

export function staffDockPopoverId(label: string) {
  return `staff-dock-group-${label.replace(/\W+/g, "-").toLowerCase()}`;
}

type StaffDockPopoverProps = {
  activeMakerspace?: Makerspace;
  activeTab: string;
  focusEdge: DockFocusEdge;
  group: StaffTabGroup;
  guestOnly: boolean;
  open: boolean;
  ownerButton: HTMLButtonElement | null;
  position: DockPopoverPosition;
  singleTenantLocked: boolean;
  tabs: readonly string[];
  unreadCount: number;
  onClose: (restoreFocus: boolean) => void;
  onFocusSettled: () => void;
  onSelect: (tab: string) => void;
};

function unreadLabel(count: number) {
  return count > 99 ? "99+" : count;
}

export function StaffDockPopover({
  activeMakerspace,
  activeTab,
  focusEdge,
  group,
  guestOnly,
  open,
  ownerButton,
  position,
  singleTenantLocked,
  tabs,
  unreadCount,
  onClose,
  onFocusSettled,
  onSelect,
}: StaffDockPopoverProps) {
  const rowRefs = useRef<Array<HTMLAnchorElement | null>>([]);

  const closeAndRestoreFocus = () => {
    onClose(false);
    window.requestAnimationFrame(() => ownerButton?.focus());
  };

  useEffect(() => {
    if (!open || !focusEdge || tabs.length === 0) return;
    const index = focusEdge === "first" ? 0 : tabs.length - 1;
    rowRefs.current[index]?.focus();
    onFocusSettled();
  }, [focusEdge, onFocusSettled, open, tabs.length]);

  const handleRowKeyDown = (event: KeyboardEvent<HTMLAnchorElement>, index: number) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeAndRestoreFocus();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;

    event.preventDefault();
    const direction = event.key === "ArrowDown" ? 1 : -1;
    const nextIndex = (index + direction + tabs.length) % tabs.length;
    rowRefs.current[nextIndex]?.focus();
  };

  return (
    <div
      id={staffDockPopoverId(group.label)}
      className="absolute max-h-[calc(100dvh-6rem)] w-64 max-w-[calc(100vw-2rem)] overflow-y-auto rounded-xl border border-line bg-panel p-2 shadow-soft-lg"
      hidden={!open}
      style={position}
    >
      {open ? (
        <div className="grid gap-1">
          {tabs.map((item, index) => (
            <Link
              key={item}
              ref={(element) => { rowRefs.current[index] = element; }}
              aria-current={activeTab === item ? "page" : undefined}
              className={`desk-nav-item min-h-11 ${activeTab === item ? "desk-nav-item-active" : ""}`}
              to={staffTabPath(item, guestOnly, activeMakerspace?.slug, singleTenantLocked)}
              onClick={() => {
                onSelect(item);
                closeAndRestoreFocus();
              }}
              onKeyDown={(event) => handleRowKeyDown(event, index)}
            >
              <span className="min-w-0 truncate">{TAB_LABELS[item] ?? item}</span>
              {item === "notifications" && unreadCount > 0 ? (
                <span className="ml-auto shrink-0 rounded-full bg-danger px-1.5 font-mono text-xs font-semibold text-bg">
                  {unreadLabel(unreadCount)}
                </span>
              ) : null}
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  );
}
