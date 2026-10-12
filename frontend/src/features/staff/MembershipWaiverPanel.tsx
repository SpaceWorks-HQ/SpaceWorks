import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Field } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { Panel } from "./panels/shared";

type Waiver = { has_waiver: boolean; version?: string; body?: string };

export function MembershipWaiverPanel({ makerspaceId }: { makerspaceId: number }) {
  const current = useQuery({ queryKey: ["members", makerspaceId, "waiver"], queryFn: () => staffRequest<Waiver>(`/admin/makerspaces/${makerspaceId}/waiver`) });
  return <Panel title="Current waiver">
    {current.isPending ? <p className="text-sm text-muted">Loading current waiver…</p> : null}
    {current.isError ? <p role="alert" className="text-sm text-danger">{current.error.message}</p> : null}
    {current.data ? <WaiverForm key={current.data.version ?? "none"} makerspaceId={makerspaceId} current={current.data} /> : null}
  </Panel>;
}

function WaiverForm({ makerspaceId, current }: { makerspaceId: number; current: Waiver }) {
  const client = useQueryClient();
  const [version, setVersion] = useState(current.version ?? "");
  const [body, setBody] = useState(current.body ?? "");
  const save = useMutation({
    mutationFn: (clear: boolean) => staffRequest(`/admin/makerspaces/${makerspaceId}/waiver`, { method: "PUT", body: JSON.stringify(clear ? { clear: true } : { version: version.trim(), body: body.trim() }) }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["members", makerspaceId] }); },
  });
  return <div className="grid gap-2">
    {!current.has_waiver ? <p className="text-sm text-muted">No active waiver.</p> : <p className="text-sm text-muted">Publishing a new version requires members to accept it again. Choose a new version label.</p>}
    <Field label="Waiver version"><input className="desk-input" maxLength={64} value={version} onChange={(event) => setVersion(event.target.value)} /></Field>
    <Field label="Waiver text"><textarea className="desk-input min-h-28" value={body} onChange={(event) => setBody(event.target.value)} /></Field>
    <div className="flex gap-2"><button className="desk-button-primary" disabled={!version.trim() || !body.trim() || save.isPending || version.trim() === current.version} onClick={() => save.mutate(false)}>{save.isPending ? "Saving…" : "Publish waiver"}</button>
      {current.has_waiver ? <button className="desk-button" disabled={save.isPending} onClick={() => save.mutate(true)}>Deactivate waiver</button> : null}</div>
    {save.isError ? <p role="alert" className="text-sm text-danger">{save.error.message}</p> : null}
  </div>;
}
