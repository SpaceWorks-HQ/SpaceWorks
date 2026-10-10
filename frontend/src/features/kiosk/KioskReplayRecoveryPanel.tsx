import { useState } from "react";
import { Panel } from "../staff/panels/shared";
import { KioskReplayDetail } from "./KioskReplayDetail";
import { KioskReplayResolution } from "./KioskReplayResolution";
import { useKioskReplays, useReplayDetail } from "./useKioskReplays";

export function KioskReplayRecoveryPanel({ makerspaceId }: { makerspaceId: number }) {
  return <RecoveryPanel key={makerspaceId} makerspaceId={makerspaceId} />;
}

function RecoveryPanel({ makerspaceId }: { makerspaceId: number }) {
  const [resolution, setResolution] = useState("unresolved");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const list = useKioskReplays(makerspaceId, resolution, page);
  const detail = useReplayDetail(selected);
  return <Panel title="Failed kiosk handovers">
    <div className="grid gap-3">
      <p className="text-sm text-muted">Review retained failed attempts for operations you may currently perform.</p>
      <label className="grid gap-1 text-sm">Recovery status<select className="desk-input" value={resolution} onChange={(event) => {
        setResolution(event.target.value); setPage(1); setSelected(null);
      }}><option value="unresolved">Unresolved</option><option value="resolved">Resolved</option><option value="all">All failures</option></select></label>
      {list.isPending ? <p role="status">Loading failed handovers…</p> : list.isError ? <div>
        <p role="alert">Failed handovers could not be loaded.</p>
        <button type="button" className="desk-button-secondary" onClick={() => { void list.refetch(); }}>Reload recovery</button>
      </div> : !list.data?.results.length ? <p>No retained failures in this view.</p> : <ul className="grid gap-2">
        {list.data.results.map((row) => <li key={row.id} className="rounded border border-line p-3">
          <button type="button" className="desk-button-secondary" aria-expanded={selected === row.id} onClick={() => setSelected(selected === row.id ? null : row.id)}>
            {row.operation_kind.replace(/_/g, " ")} · {row.station_name} · {row.failure_code}
          </button>
          {selected === row.id ? detail.isPending ? <p role="status">Loading failure details…</p> : detail.isError ? <p role="alert">This failure is unavailable under your current permissions.</p> : detail.data ? <div className="mt-3">
            <KioskReplayDetail key={row.id} row={detail.data} />
            <KioskReplayResolution key={`${row.id}/${detail.data.resolution_code}`} row={detail.data} />
          </div> : null : null}
        </li>)}
      </ul>}
      {list.data ? <nav className="flex gap-3 text-sm" aria-label="Recovery pages">
        <button type="button" className="desk-button-secondary" disabled={!list.data.previous || list.isFetching} onClick={() => { setPage(page - 1); setSelected(null); }}>Previous failures</button>
        <span>Page {page} · {list.data.count} failures</span>
        <button type="button" className="desk-button-secondary" disabled={!list.data.next || list.isFetching} onClick={() => { setPage(page + 1); setSelected(null); }}>Next failures</button>
      </nav> : null}
    </div>
  </Panel>;
}
