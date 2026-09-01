import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  collectionResults,
  deleteMachineDocument,
  getMachineDocuments,
  getMachineDocumentUrl,
  machineKeys,
  uploadMachineDocument,
} from "../../machinesApi";

export function DocumentsTab({ machineId, canEdit }: { machineId: number; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState("manual");
  const documents = useQuery({
    queryKey: machineKeys.documents(machineId),
    queryFn: () => getMachineDocuments(machineId),
  });
  const items = collectionResults(documents.data);
  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose a document to upload");
      return uploadMachineDocument(machineId, file, docType.trim());
    },
    onSuccess: async () => {
      setFile(null);
      setDocType("manual");
      if (fileInput.current) fileInput.current.value = "";
      await queryClient.invalidateQueries({ queryKey: machineKeys.documents(machineId) });
    },
  });
  const view = useMutation({
    mutationFn: (documentId: number) => getMachineDocumentUrl(documentId),
    onSuccess: ({ url }) => window.open(url, "_blank", "noopener,noreferrer"),
  });
  const remove = useMutation({
    mutationFn: deleteMachineDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: machineKeys.documents(machineId) }),
  });

  return (
    <section>
      <h3 className="title-section mb-3">Documents</h3>
      {documents.isLoading ? <p className="text-sm text-muted">Loading documents...</p> : null}
      {documents.error instanceof Error ? <p className="text-sm text-danger">{documents.error.message}</p> : null}
      {!documents.isLoading && !documents.error && !items.length ? (
        <p className="text-sm text-muted">No machine documents uploaded.</p>
      ) : null}
      <div className="grid gap-2">
        {items.map((document) => (
          <div key={document.id} className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-bg p-2 text-sm">
            <span className="min-w-0 flex-1">
              <strong className="block truncate text-ink">{document.original_filename}</strong>
              <span className="text-xs text-muted">{document.doc_type} · {formatBytes(document.size_bytes)}</span>
            </span>
            <button className="desk-button-ghost" type="button" disabled={view.isPending}
              onClick={() => view.mutate(document.id)}>View</button>
            {canEdit ? (
              <button className="desk-button-danger" type="button" disabled={remove.isPending}
                onClick={() => remove.mutate(document.id)}>Delete</button>
            ) : null}
          </div>
        ))}
      </div>
      {canEdit ? (
        <form className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_10rem_auto] sm:items-end"
          onSubmit={(event) => { event.preventDefault(); upload.mutate(); }}>
          <label className="eyebrow grid gap-1">File
            <input ref={fileInput} className="desk-input" type="file"
              accept=".pdf,.jpg,.jpeg,.png,.webp,.stl,.3mf,.step,.stp,.obj,.amf,.ply,.gcode,.gco,.iges,.igs,.dxf"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)} required />
          </label>
          <label className="eyebrow grid gap-1">Document type
            <input className="desk-input" maxLength={16} value={docType}
              onChange={(event) => setDocType(event.target.value)} required />
          </label>
          <button className="desk-button-primary" type="submit"
            disabled={upload.isPending || !file || !docType.trim()}>
            {upload.isPending ? "Uploading..." : "Upload"}
          </button>
        </form>
      ) : null}
      {upload.error instanceof Error ? <p className="mt-2 text-sm text-danger">{upload.error.message}</p> : null}
      {view.error instanceof Error ? <p className="mt-2 text-sm text-danger">{view.error.message}</p> : null}
      {remove.error instanceof Error ? <p className="mt-2 text-sm text-danger">{remove.error.message}</p> : null}
    </section>
  );
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
