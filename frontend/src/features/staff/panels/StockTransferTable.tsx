import { ErrorText } from "../../../components/ui";
import type { Transfer } from "./StockTransferPanel";

export function TransferTable({
  transfers,
  loading,
  error,
  makerspaceNames,
  sourceContainerNames,
  destinationContainerNames,
}: {
  transfers: Transfer[];
  loading: boolean;
  error?: string;
  makerspaceNames: Map<number, string>;
  sourceContainerNames: Map<number, string>;
  destinationContainerNames: Map<number, string>;
}) {
  if (loading) return <p className="text-sm text-muted">Loading transfers...</p>;
  if (error) return <ErrorText message={error} />;
  if (!transfers.length) return <p className="text-sm text-muted">No stock transfers recorded.</p>;
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="min-w-[760px] divide-y divide-line text-left text-sm">
        <thead className="eyebrow bg-surface">
          <tr>
            <th scope="col" className="px-3 py-2">ID</th>
            <th scope="col" className="px-3 py-2">Source</th>
            <th scope="col" className="px-3 py-2">Destination</th>
            <th scope="col" className="px-3 py-2">Reason</th>
            <th scope="col" className="px-3 py-2">Created</th>
            <th scope="col" className="px-3 py-2">Lines</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-bg text-ink">
          {transfers.map((transfer) => (
            <tr key={transfer.id}>
              <td className="whitespace-nowrap px-3 py-2 font-mono font-medium">#{transfer.id}</td>
              <td className="px-3 py-2"><span className="block max-w-56 break-words">{endpointLabel(transfer.source_makerspace ?? transfer.makerspace, transfer.source_container, makerspaceNames, sourceContainerNames)}</span></td>
              <td className="px-3 py-2"><span className="block max-w-56 break-words">{endpointLabel(transfer.destination_makerspace ?? transfer.makerspace, transfer.destination_container, makerspaceNames, destinationContainerNames)}</span></td>
              <td className="min-w-48 px-3 py-2 text-muted"><span className="block max-w-64 break-words">{transfer.reason}</span></td>
              <td className="whitespace-nowrap px-3 py-2 font-mono text-muted">{formatDate(transfer.created_at)}</td>
              <td className="whitespace-nowrap px-3 py-2">{transfer.lines.length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function endpointLabel(spaceId: number, containerId: number | null, spaceNames: Map<number, string>, containerNames: Map<number, string>) {
  const space = spaceNames.get(spaceId) ?? `Makerspace #${spaceId}`;
  return containerId ? `${space} / ${containerNames.get(containerId) ?? `Container #${containerId}`}` : space;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
