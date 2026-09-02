import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { memberRequest, memberRequestBlob } from "../../lib/api";

type FeedState = {
  enabled: boolean;
  token_hint: string | null;
  created_at: string | null;
  rotated_at: string | null;
};
type IssuedFeed = { feed_url: string; token_hint: string; created_at: string };

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function MemberCalendarActions({ makerspaceId, makerspaceSlug }: {
  makerspaceId: number; makerspaceSlug: string;
}) {
  const queryClient = useQueryClient();
  const [issuedUrl, setIssuedUrl] = useState<string | null>(null);
  const path = `/member/makerspaces/${makerspaceId}/event-calendar-feed/`;
  const key = ["member", makerspaceSlug, "event-calendar-feed"] as const;
  const feed = useQuery({ queryKey: key, queryFn: () => memberRequest<FeedState>(path) });
  const download = useMutation({
    mutationFn: async () => downloadBlob(
      await memberRequestBlob(`/member/makerspaces/${makerspaceId}/event-registrations/calendar.ics`),
      "my-events.ics",
    ),
  });
  const issue = useMutation({
    mutationFn: async () => {
      const result = await memberRequest<IssuedFeed>(path, {
        method: "POST", body: JSON.stringify({ confirm_bearer_risk: true }),
      });
      // Keep the bearer URL only in component state. Returning void prevents TanStack's
      // mutation cache from retaining the credential after this one-time reveal.
      setIssuedUrl(result.feed_url);
    },
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: key }),
  });
  const revoke = useMutation({
    mutationFn: () => memberRequest<void>(path, { method: "DELETE" }),
    onSuccess: async () => {
      setIssuedUrl(null);
      await queryClient.invalidateQueries({ queryKey: key });
    },
  });
  const error = feed.error || download.error || issue.error || revoke.error;

  function confirmIssue() {
    const action = feed.data?.enabled ? "replace" : "create";
    if (window.confirm(
      `This will ${action} a private calendar link. Anyone with the link can see your event schedule. Continue?`,
    )) issue.mutate();
  }

  return <div className="mt-3 rounded-md border border-line p-3 text-sm">
    <p className="font-semibold text-ink">My event calendar</p>
    <div className="mt-2 flex flex-wrap gap-2">
      <button className="desk-button" type="button" disabled={download.isPending} onClick={() => download.mutate()}>
        {download.isPending ? "Preparing…" : "Download calendar"}
      </button>
      <button className="desk-button" type="button" disabled={issue.isPending || feed.isLoading} onClick={confirmIssue}>
        {feed.data?.enabled ? "Rotate subscription link" : "Create subscription link"}
      </button>
      {feed.data?.enabled ? <button
        className="desk-button-danger" type="button" disabled={revoke.isPending}
        onClick={() => { if (window.confirm("Revoke the current calendar subscription link?")) revoke.mutate(); }}
      >Revoke link</button> : null}
    </div>
    {feed.data?.enabled && !issuedUrl ? <p className="mt-2 text-xs text-muted">
      Active private link ending in <span className="font-mono">{feed.data.token_hint}</span>. The full link is not persisted and cannot be revealed again.
    </p> : null}
    {issuedUrl ? <div className="mt-3 border-l-2 border-warn pl-3">
      <p className="font-semibold text-ink">Copy this link now. It will not be shown again.</p>
      <input className="desk-input mt-2 w-full font-mono text-xs" readOnly value={issuedUrl} aria-label="Private calendar subscription link" onFocus={(event) => event.currentTarget.select()} />
      <button className="desk-button mt-2" type="button" onClick={() => navigator.clipboard.writeText(issuedUrl).catch(() => undefined)}>Copy link</button>
      <p className="mt-2 text-xs text-danger">Treat this URL like a password. Rotate it if it is shared accidentally.</p>
    </div> : null}
    {error ? <p className="mt-2 text-xs text-danger" role="alert">{error instanceof Error ? error.message : "Calendar action failed."}</p> : null}
  </div>;
}
