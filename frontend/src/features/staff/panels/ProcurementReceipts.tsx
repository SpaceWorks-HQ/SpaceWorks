import { useId, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { staffRequest } from "../../../lib/api";

export type ToBuyReceipt = {
  id: number;
  created_at: string;
  uploaded_by: number | null;
  uploaded_by_username: string | null;
};

type UploadResponse = {
  object_key: string;
  upload: {
    url: string;
    fields?: Record<string, string>;
    method?: string;
    headers?: Record<string, string>;
  };
};

const acceptedReceiptTypes = "application/pdf,image/jpeg,image/png,image/webp";

export function ProcurementReceipts({ itemId, receipts, onChanged }: { itemId: number; receipts: ToBuyReceipt[]; onChanged: () => void }) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState("");

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) {
        await uploadReceipt(itemId, file);
      }
    },
    onSuccess: () => {
      setError("");
      if (inputRef.current) inputRef.current.value = "";
      onChanged();
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Upload failed."),
  });

  const remove = useMutation({
    mutationFn: (receiptId: number) => staffRequest<void>(`/procurement/to-buy/receipts/${receiptId}`, { method: "DELETE" }),
    onSuccess: onChanged,
    onError: (err) => setError(err instanceof Error ? err.message : "Could not delete receipt."),
  });

  async function openReceipt(receiptId: number) {
    setError("");
    try {
      const { url } = await staffRequest<{ url: string }>(`/procurement/to-buy/receipts/${receiptId}/url`);
      window.open(url, "_blank", "noopener");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open receipt.");
    }
  }

  return (
    <div className="min-w-[14rem] space-y-2">
      <div className="grid gap-1">
        {receipts.length ? receipts.map((receipt) => (
          <div key={receipt.id} className="flex min-w-0 flex-wrap items-center gap-2 rounded-md border border-line bg-surface px-2 py-1 text-xs">
            <span className="min-w-0 flex-1 font-mono text-muted">{formatDateTime(receipt.created_at)}</span>
            <button type="button" className="desk-button-ghost text-xs" onClick={() => openReceipt(receipt.id)}>View</button>
            <button type="button" className="desk-button-danger text-xs" disabled={remove.isPending} onClick={() => remove.mutate(receipt.id)}>Delete</button>
          </div>
        )) : <p className="text-xs text-muted">No receipts.</p>}
      </div>
      <label htmlFor={inputId} className="sr-only">Add receipt</label>
      <input
        id={inputId}
        ref={inputRef}
        type="file"
        multiple
        accept={acceptedReceiptTypes}
        disabled={upload.isPending}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          if (files.length) upload.mutate(files);
        }}
        className="block w-full max-w-full min-w-0 text-xs text-muted file:mr-2 file:rounded-lg file:border file:border-line file:bg-accent file:px-2 file:py-1 file:font-mono file:text-xs file:font-semibold file:text-on-accent"
      />
      {upload.isPending ? <p className="text-xs text-muted">Uploading...</p> : null}
      {error ? <p className="text-xs text-danger">{error}</p> : null}
    </div>
  );
}

async function uploadReceipt(itemId: number, file: File) {
  const presigned = await staffRequest<UploadResponse>(`/procurement/to-buy/${itemId}/receipts/presign`, {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || "application/octet-stream",
    }),
  });

  if (presigned.upload.method === "PUT") {
    const response = await fetch(presigned.upload.url, {
      method: "PUT",
      body: file,
      headers: presigned.upload.headers,
    });
    if (!response.ok) throw new Error(`Storage upload failed (${response.status})`);
  } else {
    const formData = new FormData();
    Object.entries(presigned.upload.fields ?? {}).forEach(([key, value]) => formData.append(key, value));
    formData.append("file", file);
    const response = await fetch(presigned.upload.url, { method: "POST", body: formData });
    if (!response.ok) throw new Error(`Storage upload failed (${response.status})`);
  }

  return staffRequest(`/procurement/to-buy/${itemId}/receipts`, {
    method: "POST",
    body: JSON.stringify({ object_key: presigned.object_key }),
  });
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
