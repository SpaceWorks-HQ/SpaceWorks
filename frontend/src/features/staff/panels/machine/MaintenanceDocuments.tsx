import { useRef, useState } from "react";

import { ConfirmDialog } from "../../../../components/ui";
import {
  uploadToContract,
  useDeleteMaintenanceDocument,
  useFinalizeMaintenanceDocument,
  useMaintenanceDocumentUrl,
  usePresignMaintenanceDocument,
  type MaintenanceDocument,
} from "./maintenanceApi";

export function MaintenanceDocuments({
  machineId, logId, documents, canDelete, retired,
}: {
  machineId: number;
  logId: number;
  documents: MaintenanceDocument[];
  canDelete: boolean;
  retired: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [pendingKey, setPendingKey] = useState("");
  const [uploadError, setUploadError] = useState<Error | null>(null);
  const [deleteDocumentId, setDeleteDocumentId] = useState<number | null>(null);
  const presign = usePresignMaintenanceDocument(logId);
  const finalize = useFinalizeMaintenanceDocument(machineId, logId);
  const view = useMaintenanceDocumentUrl();
  const remove = useDeleteMaintenanceDocument(machineId, logId);

  const finish = async (key: string) => {
    await finalize.mutateAsync(key);
    setPendingKey("");
    setFile(null);
    if (input.current) input.current.value = "";
  };
  const upload = async () => {
    if (!file) return;
    setUploadError(null);
    try {
      const contract = await presign.mutateAsync(file);
      await uploadToContract(file, contract);
      setPendingKey(contract.object_key);
      await finish(contract.object_key);
    } catch (caught) {
      setUploadError(caught instanceof Error ? caught : new Error("Unable to upload document."));
    }
  };
  const retryFinalize = async () => {
    setUploadError(null);
    try {
      await finish(pendingKey);
    } catch (caught) {
      setUploadError(caught instanceof Error ? caught : new Error("Unable to finalize document."));
    }
  };
  const error = uploadError ?? presign.error ?? finalize.error ?? view.error ?? remove.error;

  return (
    <div className="mt-3 grid gap-2 border-t border-line pt-3">
      <h4 className="title-section">Attachments</h4>
      {documents.map((document) => (
        <div key={document.id} className="flex flex-wrap items-center gap-2 text-xs">
          <span className="min-w-0 flex-1 text-muted">
            Attachment #{document.id} · {formatBytes(document.size_bytes)}
          </span>
          <button className="desk-button-ghost" type="button" onClick={() => view.mutate(document.id)}>
            Download
          </button>
          {canDelete && !retired ? (
            <button
              className="desk-button-danger"
              type="button"
              onClick={() => setDeleteDocumentId(document.id)}
            >
              Delete
            </button>
          ) : null}
        </div>
      ))}
      {!documents.length ? <span className="text-xs text-muted">No attachments.</span> : null}
      {!retired ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="eyebrow grid min-w-0 flex-1 gap-1">
            Add supporting document
            <input
              ref={input}
              className="desk-input"
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.webp,.stl,.3mf,.step,.stp,.obj,.amf,.ply,.gcode,.gco,.iges,.igs,.dxf"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setUploadError(null);
              }}
            />
          </label>
          <button
            className="desk-button-primary"
            type="button"
            disabled={!file || presign.isPending || finalize.isPending}
            onClick={() => void upload()}
          >
            {presign.isPending || finalize.isPending ? "Uploading..." : "Upload"}
          </button>
          {pendingKey && finalize.isError ? (
            <button className="desk-button-primary" type="button" onClick={() => void retryFinalize()}>
              Retry finalize
            </button>
          ) : null}
        </div>
      ) : null}
      {error instanceof Error ? (
        <p className="text-sm text-danger" role="alert">{error.message}</p>
      ) : null}
      <ConfirmDialog
        open={deleteDocumentId !== null}
        title="Delete maintenance attachment?"
        message="Permanently delete this maintenance attachment?"
        confirmLabel="Delete attachment"
        tone="danger"
        pending={remove.isPending}
        onConfirm={() => {
          if (deleteDocumentId !== null) {
            remove.mutate(deleteDocumentId, { onSuccess: () => setDeleteDocumentId(null) });
          }
        }}
        onCancel={() => setDeleteDocumentId(null)}
      />
    </div>
  );
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
