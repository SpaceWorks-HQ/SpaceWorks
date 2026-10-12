import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { Modal } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { TAB_LABELS } from "./staffAccess";
import { staffTabPath } from "./staffTabs";
import { quickCreateCommands } from "./quickCreate";

type Hit = { entity: string; id: number; label: string; tab: string; query: Record<string, string> };
type Command = { key: string; label: string; tab: string; query?: Record<string, string> };

export function CommandPalette({ makerspaceId, makerspaceSlug, allowedTabs, guestOnly, singleTenantLocked, ownerName, actions = [], isSuperadmin = false }: {
  makerspaceId: number; makerspaceSlug: string; allowedTabs: readonly string[]; guestOnly: boolean; singleTenantLocked: boolean; ownerName: string;
  actions?: readonly string[]; isSuperadmin?: boolean;
}) {
  const navigate = useNavigate();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(0);
  const term = useDebouncedValue(search, 250).trim();
  const results = useQuery({
    queryKey: ["staff-search", ownerName, makerspaceId, term],
    queryFn: ({ signal }) => staffRequest<{ results: Hit[] }>(`/admin/search?makerspace_id=${makerspaceId}&q=${encodeURIComponent(term)}`, { signal }),
    enabled: open && term.length >= 2,
    staleTime: 0,
  });
  const commands: Command[] = allowedTabs.filter((tab) => (TAB_LABELS[tab] ?? tab).toLowerCase().includes(search.toLowerCase().trim()))
    .map((tab) => ({ key: `tab-${tab}`, label: `Go to ${TAB_LABELS[tab] ?? tab}`, tab }));
  commands.push(...quickCreateCommands(actions, allowedTabs, isSuperadmin).filter(command => command.label.toLowerCase().includes(search.toLowerCase().trim())));
  if (term === search.trim() && term.length >= 2) results.data?.results.filter((hit) => allowedTabs.includes(hit.tab)).forEach((hit) => commands.push({ key: `${hit.entity}-${hit.id}`, label: `${TAB_LABELS[hit.tab] ?? hit.entity}: ${hit.label}`, tab: hit.tab, query: hit.query }));
  const current = Math.min(active, Math.max(0, commands.length - 1));
  useEffect(() => {
    if (open) document.getElementById(`${id}-option-${current}`)?.scrollIntoView?.({ block: "nearest" });
  }, [open, id, current, commands.length]);

  const close = () => { setOpen(false); setSearch(""); setActive(0); };
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        // Keep the existing dialog stack intact when evidence/action dialogs own focus.
        if (!open && document.querySelector('[role="dialog"]')) return;
        setOpen((value) => !value); setSearch(""); setActive(0);
      }
    };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, [open]);
  useEffect(() => { setOpen(false); setSearch(""); setActive(0); }, [makerspaceId, ownerName]);

  const run = (command?: Command) => {
    if (!command) return;
    const path = staffTabPath(command.tab, guestOnly, makerspaceSlug, singleTenantLocked);
    const query = command.query ? new URLSearchParams(command.query).toString() : "";
    close();
    navigate(path + (query ? `?${query}` : ""));
  };
  return <>
    <button type="button" className="desk-button-ghost ml-5" onClick={() => setOpen(true)} aria-haspopup="dialog">Search and commands <kbd>Ctrl/⌘ K</kbd></button>
    {open ? <Modal open onClose={close} title="Search and commands">
      <label htmlFor={`${id}-input`} className="sr-only">Search staff console</label>
      <input id={`${id}-input`} className="desk-input w-full" role="combobox" aria-autocomplete="list" aria-expanded="true" aria-controls={`${id}-list`} aria-activedescendant={commands.length ? `${id}-option-${current}` : undefined}
        value={search} maxLength={100} onChange={(event) => { setSearch(event.target.value); setActive(0); }}
        onKeyDown={(event) => {
          if (["ArrowDown", "ArrowUp", "Home", "End", "Enter"].includes(event.key)) event.preventDefault();
          if (event.key === "ArrowDown") setActive(commands.length ? (current + 1) % commands.length : 0);
          if (event.key === "ArrowUp") setActive(commands.length ? (current + commands.length - 1) % commands.length : 0);
          if (event.key === "Home") setActive(0);
          if (event.key === "End") setActive(Math.max(0, commands.length - 1));
          if (event.key === "Enter") run(commands[current]);
        }} />
      <div role="status" aria-live="polite" className="my-2 text-xs text-muted">{results.isFetching ? "Searching…" : `${commands.length} commands and results`}</div>
      {results.error && term.length >= 2 ? <p role="alert" className="text-sm text-danger">Search unavailable: {results.error.message}</p> : null}
      <ul id={`${id}-list`} role="listbox" aria-label="Commands and results" className="max-h-80 overflow-y-auto">
        {commands.map((command, index) => <li key={command.key} id={`${id}-option-${index}`} role="option" aria-selected={index === current}
          className={`cursor-pointer rounded p-3 ${index === current ? "bg-surface font-semibold" : ""}`}
          onMouseDown={(event) => event.preventDefault()} onClick={() => run(command)}>{command.label}</li>)}
      </ul>
      {!commands.length && !results.isFetching ? <p className="text-sm text-muted">No matching commands or results.</p> : null}
    </Modal> : null}
  </>;
}
