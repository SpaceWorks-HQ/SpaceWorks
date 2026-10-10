import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAccessToken, memberRequest } from "../../lib/api";
import { MemberCertifications } from "./MemberCertifications";
import { MemberActivityPanel, type MemberActivity } from "./MemberActivity";
import { presenceStartLocation } from "./geolocation";

// UI discovery only. Authorization and session validity remain server-enforced.
export function hasClaimSession() {
  try {
    const payload = getAccessToken()?.split(".")[1];
    return Boolean(payload && JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))).token_type === "claim_access");
  } catch { return false; }
}

export function MemberClaimSession({ slug, makerspaceId, modules, geofenceEnabled }: {
  slug: string; makerspaceId: number; modules: string[]; geofenceEnabled: boolean;
}) {
  const client = useQueryClient();
  const key = ["member", "claim", makerspaceId];
  const presence = useQuery({ queryKey: [...key, "presence"], queryFn: () => memberRequest<{ active: boolean }>(`/public/${slug}/presence-sessions/current`) });
  const waiver = useQuery({ queryKey: [...key, "waiver"], queryFn: () => memberRequest<{ has_waiver: boolean; body?: string; version?: string }>(`/member/makerspaces/${makerspaceId}/waiver`) });
  const activity = useQuery({ queryKey: [...key, "activity"], queryFn: () => memberRequest<MemberActivity>(`/member/makerspaces/${makerspaceId}/activity`), enabled: modules.includes("membership") });
  const togglePresence = useMutation({ mutationFn: async () => {
    if (presence.data?.active) return memberRequest(`/public/${slug}/presence-sessions/current/end`, { method: "POST" });
    const location = await presenceStartLocation(geofenceEnabled);
    return memberRequest(`/public/${slug}/presence-sessions`, { method: "POST", body: JSON.stringify({ duration_minutes: 120, ...(location ?? {}) }) });
  }, onSuccess: () => { void client.invalidateQueries({ queryKey: key }); } });
  const error = presence.error ?? waiver.error ?? activity.error ?? togglePresence.error;
  return <main className="desk-shell mx-auto max-w-3xl space-y-5 px-5 py-8">
    <section className="desk-panel p-5"><h1 className="title-page">Temporary member session</h1><p className="mt-2 text-sm text-muted">Your staff-issued claim code opened access for this makerspace. Staff must witness waiver acceptance.</p>
      {modules.includes("public_inventory") ? <Link className="desk-button-secondary mt-3 inline-flex" to={`/m/${slug}`}>Browse tools</Link> : null}
    </section>
    {waiver.data?.has_waiver ? <section className="desk-panel p-5"><h2 className="title-panel">Current waiver ({waiver.data.version})</h2><p className="mt-2 whitespace-pre-wrap text-sm text-muted">{waiver.data.body}</p><p className="mt-3 text-sm text-muted">Ask staff to record witnessed acceptance before borrowing.</p></section> : null}
    <section className="desk-panel p-5"><h2 className="title-panel">Presence</h2>
      {presence.isPending ? <p className="text-sm text-muted">Loading presence…</p> : null}
      {presence.data ? <button className="desk-button-secondary mt-3" disabled={togglePresence.isPending} onClick={() => togglePresence.mutate()}>{togglePresence.isPending ? "Updating…" : presence.data.active ? "End presence" : "Start presence"}</button> : null}
    </section>
    {activity.isLoading ? <p className="text-sm text-muted">Loading your activity…</p> : null}
    {modules.includes("machines") ? <MemberCertifications makerspaceId={makerspaceId} /> : null}
    {activity.data ? <MemberActivityPanel activity={activity.data} makerspaceId={makerspaceId} makerspaceSlug={slug} /> : null}
    {error ? <p role="alert" className="text-sm text-danger">{error.message}</p> : null}
  </main>;
}
