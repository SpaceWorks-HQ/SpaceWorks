import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ErrorText, Field } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { Pagination } from "../../../components/ui/Pagination";
import { usePaginatedQuery } from "../../../lib/usePaginatedQuery";
import { Panel, type Makerspace, type Product, useStaffGet } from "./shared";
import { TransferTable } from "./StockTransferTable";
import { invalidateContainerViews, invalidateInventoryViews } from "../queryInvalidation";

type ListResponse<T> = { count?: number; results: T[] };
type Container = { id: number; code?: string; label: string; location?: string };
type TransferLine = { id: number; product: number | null; asset: number | null; quantity: number };
export type Transfer = {
  id: number;
  makerspace: number;
  source_container: number | null;
  destination_container: number | null;
  source_makerspace: number | null;
  destination_makerspace: number | null;
  reason: string;
  status: string;
  created_at: string;
  lines: TransferLine[];
};
type LineDraft = { key: number; productId: string; quantity: string };

export function StockTransferPanel({
  makerspace,
  makerspaces,
  isSuperadmin,
  canEditInventory = false,
}: {
  makerspace: Makerspace;
  makerspaces: Makerspace[];
  isSuperadmin: boolean;
  canEditInventory?: boolean;
}) {
  const queryClient = useQueryClient();
  // EDIT_INVENTORY holders can run INTRA-makerspace relocations; only a superadmin gets the
  // source/destination makerspace selectors (cross-makerspace moves are superadmin-only).
  const canCreate = isSuperadmin || canEditInventory;
  const spaceOptions = makerspaces.length ? makerspaces : [makerspace];
  const [sourceMakerspaceId, setSourceMakerspaceId] = useState(makerspace.id);
  const [destinationMakerspaceId, setDestinationMakerspaceId] = useState(makerspace.id);
  const [sourceContainerId, setSourceContainerId] = useState("");
  const [destinationContainerId, setDestinationContainerId] = useState("");
  const [reason, setReason] = useState("");
  const [lineRows, setLineRows] = useState<LineDraft[]>([{ key: 1, productId: "", quantity: "1" }]);
  const [nextLineKey, setNextLineKey] = useState(2);
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    setSourceMakerspaceId(makerspace.id);
    setDestinationMakerspaceId(makerspace.id);
    setSourceContainerId("");
    setDestinationContainerId("");
    setLineRows([{ key: 1, productId: "", quantity: "1" }]);
    setNextLineKey(2);
    setValidationError("");
  }, [makerspace.id]);

  const products = useStaffGet<ListResponse<Product>>(
    ["inventory", sourceMakerspaceId],
    `/admin/makerspace/${sourceMakerspaceId}/inventory?page_size=1000`,
    canCreate,
  );
  const transfers = usePaginatedQuery<Transfer>({
    key: ["transfers", sourceMakerspaceId],
    path: `/admin/makerspace/${sourceMakerspaceId}/stock-transfers`,
    resetKey: String(sourceMakerspaceId),
  });
  const sourceContainers = useStaffGet<ListResponse<Container>>(
    ["containers", sourceMakerspaceId],
    `/admin/makerspace/${sourceMakerspaceId}/containers?page_size=1000`,
    canCreate,
  );
  const destinationContainers = useStaffGet<ListResponse<Container>>(
    ["containers", destinationMakerspaceId],
    `/admin/makerspace/${destinationMakerspaceId}/containers?page_size=1000`,
    canCreate,
  );

  const makerspaceNames = useMemo(
    () => new Map(spaceOptions.map((space) => [space.id, space.name])),
    [spaceOptions],
  );
  const sourceContainerNames = useMemo(
    () => new Map((sourceContainers.data?.results ?? []).map((box) => [box.id, labelForContainer(box)])),
    [sourceContainers.data?.results],
  );
  const destinationContainerNames = useMemo(
    () => new Map((destinationContainers.data?.results ?? []).map((box) => [box.id, labelForContainer(box)])),
    [destinationContainers.data?.results],
  );

  const isCrossMakerspace = destinationMakerspaceId !== sourceMakerspaceId;

  const create = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/makerspace/${sourceMakerspaceId}/stock-transfers`, {
        method: "POST",
        body: JSON.stringify({
          // Cross-makerspace transfers ignore the source container (and the control is
          // disabled), so never send a stale value the backend would otherwise record.
          source_container_id:
            isCrossMakerspace || !sourceContainerId ? null : Number(sourceContainerId),
          // destination_container_id is resolved within the destination makerspace
          // (same makerspace for intra-transfers), so it is valid in both modes.
          destination_container_id: destinationContainerId ? Number(destinationContainerId) : null,
          destination_makerspace_id: isCrossMakerspace ? destinationMakerspaceId : null,
          reason: reason.trim(),
          lines: lineRows.map((line) => ({
            product_id: Number(line.productId),
            quantity: Number(line.quantity),
          })),
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transfers", sourceMakerspaceId] });
      invalidateInventoryViews(queryClient, sourceMakerspaceId);
      invalidateContainerViews(queryClient, sourceMakerspaceId, sourceContainerId ? Number(sourceContainerId) : undefined);
      if (destinationMakerspaceId !== sourceMakerspaceId) {
        queryClient.invalidateQueries({ queryKey: ["transfers", destinationMakerspaceId] });
        invalidateInventoryViews(queryClient, destinationMakerspaceId);
      }
      invalidateContainerViews(queryClient, destinationMakerspaceId, destinationContainerId ? Number(destinationContainerId) : undefined);
      setSourceContainerId("");
      setDestinationContainerId("");
      setReason("");
      setLineRows([{ key: 1, productId: "", quantity: "1" }]);
      setNextLineKey(2);
      setValidationError("");
    },
  });

  const changeSource = (nextId: number) => {
    setSourceMakerspaceId(nextId);
    setDestinationMakerspaceId(nextId);
    setSourceContainerId("");
    setDestinationContainerId("");
    setLineRows([{ key: 1, productId: "", quantity: "1" }]);
    setNextLineKey(2);
    setValidationError("");
  };

  const addLine = () => {
    setLineRows((rows) => [...rows, { key: nextLineKey, productId: "", quantity: "1" }]);
    setNextLineKey((key) => key + 1);
  };

  const updateLine = (key: number, patch: Partial<LineDraft>) => {
    setLineRows((rows) => rows.map((line) => (line.key === key ? { ...line, ...patch } : line)));
  };

  const removeLine = (key: number) => {
    setLineRows((rows) => rows.filter((line) => line.key !== key));
  };

  const submit = () => {
    const invalidQuantity = lineRows.some((line) => !Number.isInteger(Number(line.quantity)) || Number(line.quantity) < 1);
    if (!reason.trim()) setValidationError("Reason is required.");
    else if (!lineRows.length) setValidationError("Add at least one transfer line.");
    else if (lineRows.some((line) => !line.productId)) setValidationError("Choose a product for every line.");
    else if (invalidQuantity) setValidationError("Quantities must be whole numbers of at least 1.");
    else {
      setValidationError("");
      create.mutate();
    }
  };

  return (
    <Panel title="Stock transfers">
      <div className="grid gap-4">
        {!canCreate ? (
          <p className="rounded-md border border-line bg-warn px-3 py-2 text-sm text-on-warn dark:bg-warn/15 dark:text-warn-ink">
            Transfers are managed by inventory staff. This view is read-only.
          </p>
        ) : (
          <form
            className="rounded-md border border-line bg-surface p-3"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            <div className="grid gap-3 lg:grid-cols-2">
              {isSuperadmin ? (
                <>
                  <Field label="Source makerspace">
                    <select className="desk-input w-full" value={sourceMakerspaceId} onChange={(event) => changeSource(Number(event.target.value))}>
                      {spaceOptions.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
                    </select>
                  </Field>
                  <Field label="Destination makerspace">
                    <select className="desk-input w-full" value={destinationMakerspaceId} onChange={(event) => { setDestinationMakerspaceId(Number(event.target.value)); setDestinationContainerId(""); }}>
                      {spaceOptions.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
                    </select>
                  </Field>
                </>
              ) : null}
              <Field label="Source container">
                <select className="desk-input w-full" value={sourceContainerId} disabled={isCrossMakerspace || sourceContainers.isLoading} onChange={(event) => setSourceContainerId(event.target.value)}>
                  <option value="">Any source container</option>
                  {sourceContainers.data?.results?.map((box) => <option key={box.id} value={box.id}>{labelForContainer(box)}</option>)}
                </select>
                {isCrossMakerspace ? (
                  <p className="mt-1 text-xs text-muted">
                    Source container is ignored for makerspace-to-makerspace transfers.
                  </p>
                ) : null}
              </Field>
              <Field label="Destination container">
                <select className="desk-input w-full" value={destinationContainerId} disabled={destinationContainers.isLoading} onChange={(event) => setDestinationContainerId(event.target.value)}>
                  <option value="">No destination container</option>
                  {destinationContainers.data?.results?.map((box) => <option key={box.id} value={box.id}>{labelForContainer(box)}</option>)}
                </select>
              </Field>
            </div>

            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <h3 className="title-section">Transfer lines</h3>
                <button className="desk-button-ghost" type="button" onClick={addLine}>Add line</button>
              </div>
              <div className="grid gap-2">
                {lineRows.map((line, index) => (
                  <div key={line.key} className="grid gap-2 md:grid-cols-[1fr_120px_auto]">
                    <Field label={`Product for transfer line ${index + 1}`}><select className="desk-input" value={line.productId} disabled={products.isLoading} onChange={(event) => updateLine(line.key, { productId: event.target.value })}>
                      <option value="">Product</option>
                      {products.data?.results?.map((product) => <option key={product.id} value={product.id}>{product.name} ({product.available_quantity} available)</option>)}
                    </select></Field>
                    <Field label={`Quantity for transfer line ${index + 1}`}><input className="desk-input" min={1} inputMode="numeric" type="number" value={line.quantity} onChange={(event) => updateLine(line.key, { quantity: event.target.value })} /></Field>
                    <button className="desk-button-danger" type="button" onClick={() => removeLine(line.key)}>Remove</button>
                  </div>
                ))}
              </div>
            </div>

            <Field label="Reason" className="mt-4">
              <input className="desk-input w-full" value={reason} placeholder="Why is this stock moving?" onChange={(event) => setReason(event.target.value)} />
            </Field>
            {isCrossMakerspace ? (
              <p className="mt-4 rounded-md border border-accent/40 bg-accent/10 px-3 py-2 text-sm text-accent-ink">
                Inter-makerspace transfer: the chosen quantity is deducted from this makerspace and
                credited to a matching product in the destination makerspace (created there if
                needed, kept private until it opts in). Only available stock can move; individual
                asset-tracked products are not supported.
              </p>
            ) : null}
            {validationError ? <ErrorText message={validationError} /> : null}
            {create.isError ? <ErrorText message={create.error.message} /> : null}
            {products.isError ? <ErrorText message={products.error.message} /> : null}
            {sourceContainers.isError ? <ErrorText message={sourceContainers.error.message} /> : null}
            {destinationContainers.isError ? <ErrorText message={destinationContainers.error.message} /> : null}
            <button className="desk-button-primary mt-4" type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating..." : "Create transfer"}
            </button>
          </form>
        )}

        <TransferTable
          transfers={transfers.results}
          loading={transfers.isLoading}
          error={transfers.error?.message}
          makerspaceNames={makerspaceNames}
          sourceContainerNames={sourceContainerNames}
          destinationContainerNames={destinationContainerNames}
        />
        <Pagination page={transfers.page} totalPages={transfers.totalPages} onChange={transfers.setPage} count={transfers.count} pageSize={transfers.pageSize} />
      </div>
    </Panel>
  );
}

function labelForContainer(container: Container) {
  return [container.code, container.label, container.location].filter(Boolean).join(" - ");
}
