import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { memberRequest, memberRequestBlob, staffRequest, staffRequestBlob } from "../../lib/api";

export type PaymentDocument = {
  id: number; payment: number; number: string; kind: "receipt" | "credit_note";
  amount: string; currency: string; issued_at: string; money_at: string;
};
type DocumentPage = { count: number; next: string | null; previous: string | null; results: PaymentDocument[] };

export function PaymentDocuments({ makerspaceId, audience }: { makerspaceId: number; audience: "member" | "staff" }) {
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState(false);
  const request = audience === "member" ? memberRequest : staffRequest;
  const base = audience === "member" ? `/member/makerspaces/${makerspaceId}` : `/admin/makerspace/${makerspaceId}`;
  const documents = useQuery({
    queryKey: ["payment-documents", audience, makerspaceId, page],
    queryFn: () => request<DocumentPage>(`${base}/payment-documents?page=${page}`),
    enabled: expanded,
  });
  const download = useMutation({
    mutationFn: async (document: PaymentDocument) => {
      const grant = await request<{ url: string; expires_in: number }>(`${base}/payment-documents/${document.id}/download-url`);
      // Grants contain a server route (/api/v1/...), whereas API helpers take a
      // path relative to that prefix. Authentication is required even with the grant.
      const path = grant.url.replace(/^\/api\/v1/, "");
      const blob = await (audience === "member" ? memberRequestBlob(path) : staffRequestBlob(path));
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = `payment-document-${document.id}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    },
  });
  return <section className="mt-4 border-t border-line pt-4" aria-label="Receipt documents">
    <h3 className="font-semibold text-ink">Receipts and credit notes</h3>
    <button className="desk-button-secondary" type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "Hide documents" : "Show documents"}</button>
    {expanded ? <>
    {documents.isLoading ? <p className="text-sm text-muted">Loading documents...</p> : null}
    {documents.error || download.error ? <p role="alert" className="text-sm text-danger">{(documents.error || download.error)?.message}</p> : null}
    {documents.data?.count === 0 ? <p className="text-sm text-muted">No issued documents.</p> : null}
    <ul className="space-y-2">{documents.data?.results.map((document) => <li key={document.id} className="flex flex-wrap items-center gap-2 text-sm">
      <span>{document.kind === "receipt" ? "Receipt" : "Credit note"} {document.number}</span>
      <span className="font-mono">{document.currency.toUpperCase()} {document.amount}</span>
      <button className="desk-button-secondary" type="button" disabled={download.isPending} onClick={() => download.mutate(document)}>Download PDF</button>
    </li>)}</ul>
    {documents.data && documents.data.count > 24 ? <div className="mt-2 flex items-center gap-2">
      <button className="desk-button-secondary" type="button" disabled={!documents.data.previous} onClick={() => setPage(page - 1)}>Previous</button>
      <span>Page {page}</span>
      <button className="desk-button-secondary" type="button" disabled={!documents.data.next} onClick={() => setPage(page + 1)}>Next</button>
    </div> : null}
    </> : null}
  </section>;
}
