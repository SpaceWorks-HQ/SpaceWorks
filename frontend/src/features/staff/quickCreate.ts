import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

export function quickCreateCommands(actions: readonly string[], tabs: readonly string[], superadmin = false) {
  return [
    { key: "new-request", label: "New request / direct handout", tab: "direct", action: "issue_direct_loan", kind: "request" },
    { key: "new-item", label: "New item", tab: "inventory", action: "edit_inventory", kind: "item" },
    { key: "new-event", label: "New event", tab: "events", action: "manage_events", kind: "event" },
    { key: "new-booking", label: "New booking", tab: "bookings", action: "manage_bookings", kind: "booking" },
  ].filter(command => tabs.includes(command.tab) && (superadmin || actions.includes(command.action)))
    .map(command => ({ ...command, query: { create: command.kind } }));
}

/** Consume once so Back does not reopen a completed form. */
export function useQuickCreate(kind: string, open: () => void) {
  const [params, setParams] = useSearchParams();
  const requested = params.get("create") === kind;
  useEffect(() => {
    if (!requested) return;
    open();
    setParams(current => { const next = new URLSearchParams(current); next.delete("create"); return next; }, { replace: true });
  }, [requested]);
}
