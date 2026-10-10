import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { devicesApi, type EnrollmentGrant } from "../devicesApi";
import { deviceQueryKeys } from "../deviceQueryKeys";
import { DeviceCreateForm, DeviceIdentitySection } from "./DeviceIdentitySection";
import { DeviceEnrollmentModal } from "./DeviceEnrollmentModal";
import { Panel } from "./shared";

export function DevicesPanel({ makerspaceId }: { makerspaceId: number }) {
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [grant, setGrant] = useState<EnrollmentGrant | null>(null);
  const devices = useQuery({
    queryKey: deviceQueryKeys.list(makerspaceId, page),
    queryFn: () => devicesApi.list(makerspaceId, page),
    refetchInterval: 60_000,
  });
  const detail = useQuery({
    queryKey: deviceQueryKeys.detail(makerspaceId, selectedId ?? ""),
    queryFn: () => devicesApi.detail(selectedId!),
    enabled: selectedId !== null,
    refetchInterval: 60_000,
  });
  return <Panel title="Devices">
    <DeviceCreateForm makerspaceId={makerspaceId} onGrant={setGrant} />
    {devices.isPending ? <p role="status">Loading devices...</p> : devices.isError ? <div role="alert">
      Could not load devices. <button className="desk-button" onClick={() => void devices.refetch()}>Retry devices</button>
    </div> : <>
      {!devices.data.results.length ? <p>No devices yet.</p> : <div className="overflow-x-auto">
        <table className="w-full text-left"><caption className="sr-only">Connected device identities and status</caption>
          <thead><tr><th scope="col">Name</th><th scope="col">Kind</th><th scope="col">State</th><th scope="col">Last seen</th></tr></thead>
          <tbody>{devices.data.results.map((device) => <tr key={device.id}>
            <td><button className="desk-button" aria-pressed={selectedId === device.id} onClick={() => setSelectedId(device.id)}>{device.name}</button></td>
            <td>{device.kind.replace(/_/g, " ")}</td>
            <td>{device.status === "active" ? device.offline_since ? "Offline" : "Active" : device.status}</td>
            <td>{device.last_seen_at ? new Date(device.last_seen_at).toLocaleString() : "No heartbeat yet"}</td>
          </tr>)}</tbody>
        </table>
      </div>}
      <nav className="mt-3 flex items-center gap-3" aria-label="Device pages">
        <button className="desk-button" disabled={!devices.data.previous || devices.isFetching} onClick={() => { setSelectedId(null); setPage((p) => p - 1); }}>Previous</button>
        <span role="status">Page {page} | {devices.data.count} devices</span>
        <button className="desk-button" disabled={!devices.data.next || devices.isFetching} onClick={() => { setSelectedId(null); setPage((p) => p + 1); }}>Next</button>
      </nav>
    </>}
    {selectedId && detail.isPending ? <p role="status">Loading device details...</p> : null}
    {selectedId && detail.isError ? <div role="alert">Could not load device details. <button className="desk-button" onClick={() => void detail.refetch()}>Retry detail</button></div> : null}
    {detail.data && selectedId ? <DeviceIdentitySection key={`${detail.data.id}:${detail.data.name}:${detail.data.offline_threshold_seconds}`} device={detail.data} onGrant={setGrant} /> : null}
    {grant ? <DeviceEnrollmentModal key={grant.enrollment_id} grant={grant} onClose={() => setGrant(null)} /> : null}
  </Panel>;
}
