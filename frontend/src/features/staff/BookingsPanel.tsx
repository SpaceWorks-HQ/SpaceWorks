import { useState } from "react";

import { Badge, DataTable, Modal, type DataTableColumn } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import { BookableSpaceForm } from "./BookableSpaceForm";
import { BookingDrawer } from "./BookingDrawer";
import { useBookableSpaces, useCreateBookableSpace, type BookableSpace } from "./bookingsApi";
import { Panel } from "./panels/shared";

const columns = (onOpen: (id: number) => void): DataTableColumn<BookableSpace>[] => [
  {
    key: "name",
    header: "Space",
    sortable: true,
    render: (space) => <button className="desk-button-ghost h-auto flex-col items-start px-0 text-left" type="button" onClick={() => onOpen(space.id)}>{space.name}<span className="mt-1 block text-xs font-normal text-muted">{space.location || "No location label"}</span></button>,
  },
  { key: "kind", header: "Type", render: (space) => space.kind.replace("_", " ") },
  { key: "approval_mode", header: "Approval", render: (space) => space.approval_mode === "approve" ? "Staff approval" : "Instant" },
  { key: "is_public", header: "Public", render: (space) => <Badge tone={space.is_public ? "success" : "neutral"}>{space.is_public ? "Public" : "Private"}</Badge> },
  { key: "is_active", header: "Status", render: (space) => <Badge tone={space.is_active ? "success" : "neutral"}>{space.is_active ? "Active" : "Inactive"}</Badge> },
];

export function BookingsPanel({ makerspaceId }: { makerspaceId: number }) {
  const [page, setPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const spaces = useBookableSpaces(makerspaceId, page);
  const create = useCreateBookableSpace(makerspaceId);
  const apiError = spaces.error instanceof StructuredApiError ? spaces.error : null;

  if (apiError?.status === 403) return <Panel title="Bookings"><p className="text-sm text-muted">Only Space Managers can manage bookings.</p></Panel>;
  if (apiError?.status === 400) return <Panel title="Bookings"><p className="text-sm text-muted">The Bookings module is not enabled for this makerspace.</p></Panel>;

  return (
    <Panel title="Bookings">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div><h3 className="title-section">Bookable spaces</h3><p className="mt-1 text-sm text-muted">Manage public settings, forms, and booking requests.</p></div>
        <button className="desk-button-primary" type="button" onClick={() => setCreateOpen(true)}>Create space</button>
      </div>
      {spaces.error ? <p className="mb-3 text-sm text-danger" role="alert">{spaces.error.message}</p> : null}
      <DataTable columns={columns(setSelectedId)} data={spaces.data?.results ?? []} loading={spaces.isLoading} skeletonCols={5} emptyTitle="No bookable spaces" emptyDescription="Create a space to start accepting bookings." />
      {spaces.data ? <div className="mt-3 flex items-center justify-between gap-2"><span className="font-mono text-xs text-muted">Page {page} - {spaces.data.count} total</span><div className="flex gap-2"><button className="desk-button" type="button" disabled={!spaces.data.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</button><button className="desk-button" type="button" disabled={!spaces.data.next} onClick={() => setPage((value) => value + 1)}>Next</button></div></div> : null}
      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Create bookable space" size="xl">
        <BookableSpaceForm
          onSubmit={(payload) => create.mutate(payload, { onSuccess: (space) => { setCreateOpen(false); setSelectedId(space.id); } })}
          pending={create.isPending}
          error={create.error?.message}
          submitLabel="Create space"
        />
        <button className="desk-button mt-3" type="button" disabled={create.isPending} onClick={() => setCreateOpen(false)}>Cancel</button>
      </Modal>
      {selectedId !== null ? <BookingDrawer key={selectedId} makerspaceId={makerspaceId} spaceId={selectedId} onClose={() => setSelectedId(null)} /> : null}
    </Panel>
  );
}
