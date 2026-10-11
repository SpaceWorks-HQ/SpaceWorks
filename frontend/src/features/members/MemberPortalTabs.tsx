import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

export const MEMBER_TABS = ["overview", "loans", "bookings", "events", "payments", "inbox", "account"] as const;
export type MemberTab = typeof MEMBER_TABS[number];

export function memberTabs(modules: string[]) {
  return MEMBER_TABS.filter((tab) => {
    if (["overview", "payments", "account"].includes(tab)) return true;
    if (!modules.includes("membership")) return false;
    if (tab === "loans") return modules.includes("request_workflow");
    if (tab === "bookings" || tab === "events") return modules.includes(tab);
    return true;
  });
}

export function useMemberTab(modules: string[]) {
  const location = useLocation();
  const requested = location.pathname.match(/^((?:\/m\/[^/]+)?\/member)(?:\/([^/]+))?\/?$/)?.[2];
  const tabs = memberTabs(modules);
  return tabs.find((tab) => tab === requested) ?? "overview";
}

export function MemberPortalTabs({ modules, active, children }: { modules: string[]; active: MemberTab; children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const refs = useRef<(HTMLAnchorElement | null)[]>([]);
  const base = location.pathname.match(/^((?:\/m\/[^/]+)?\/member)(?:\/[^/]+)?\/?$/)?.[1] ?? "/member";
  const tabs = memberTabs(modules);
  const path = (tab: MemberTab) => `${base}/${tab}`;
  function keyDown(event: KeyboardEvent, index: number) {
    const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
      : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
        : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    refs.current[next]?.focus();
    navigate(path(tabs[next]));
  }
  return <>
    <div role="tablist" aria-label="Member portal" className="flex flex-wrap gap-2">
      {tabs.map((tab, index) => <Link key={tab} ref={(node) => { refs.current[index] = node; }}
        role="tab" id={`member-tab-${tab}`} aria-controls="main-content" aria-selected={active === tab}
        tabIndex={active === tab ? 0 : -1} className={active === tab ? "desk-button-secondary" : "desk-button"}
        to={path(tab)} onKeyDown={(event) => keyDown(event, index)}>{tab[0].toUpperCase() + tab.slice(1)}</Link>)}
    </div>
    <section role="tabpanel" id="main-content" aria-labelledby={`member-tab-${active}`} tabIndex={-1} className="space-y-5 focus-visible:outline-2 focus-visible:outline-focus">
      {children}
    </section>
  </>;
}
