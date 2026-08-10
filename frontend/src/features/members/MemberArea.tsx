import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import type { MembershipOutcome, MembershipPolicyEnum } from "../../generated/api";
import { bootstrapTenant, fetchMe, refreshAccessToken, StructuredApiError, staffRequest } from "../../lib/api";
import { MemberAuthPanel } from "./MemberAuthPanel";
import { JoinMembershipCta } from "./JoinMembershipCta";
import { presenceStartLocation } from "./geolocation";
import { MemberActivityPanel, type MemberActivity } from "./MemberActivity";
import { MemberDirectory } from "./MemberDirectory";
import { MemberProfilePanel } from "./MemberProfilePanel";
import { MemberReferrals, type ClaimableInvitation } from "./MemberReferrals";

type Membership = { makerspace: { slug: string; name: string }; membership_status: string; role: string; waiver_acceptance_required: boolean; can_refer: boolean; can_verify: boolean; verified_at: string | null; referrals_enabled: boolean };
type Memberships = { memberships: Membership[]; requests: { makerspace: { slug: string; name: string }; state: string; kind: string }[] };
type Waiver = { has_waiver: boolean; body?: string; version?: string };
type Presence = { active: boolean; session: { expires_at: string } | null };
type Invitations = { invitations: ClaimableInvitation[] };
type ReferralOutcome = { state: "invited" };
type ClaimOutcome = { id: number; outcome: "active" | "pending_approval" };
type MemberPayment = { id: number; subject_label: string; status: string; checkout_url: string; created_at: string };

function message(error: unknown) {
  if (error instanceof StructuredApiError && error.status === 401) return "Sign in to manage your membership.";
  return error instanceof Error ? error.message : "Unable to complete that action.";
}

export function MemberArea() {
  const { slug = "" } = useParams();
  const client = useQueryClient();
  const [restoring, setRestoring] = useState(true);
  const [showSignIn, setShowSignIn] = useState(false);
  useEffect(() => {
    refreshAccessToken().then(() => client.invalidateQueries({ queryKey: ["member"] })).finally(() => setRestoring(false));
  }, [client]);
  const bootstrap = useQuery({ queryKey: ["member", slug, "bootstrap"], queryFn: () => bootstrapTenant({ slug: slug || undefined }), retry: false });
  const resolvedSlug = slug || bootstrap.data?.makerspace.slug || "";
  const makerspaceId = bootstrap.data?.makerspace.id ?? -1;
  const memberships = useQuery({ queryKey: ["member", "memberships"], queryFn: () => staffRequest<Memberships>("/memberships/me"), retry: false });
  const unauthenticated = memberships.error instanceof StructuredApiError && memberships.error.status === 401;
  const membership = memberships.data?.memberships.find((row) => row.makerspace.slug === resolvedSlug);
  const requested = memberships.data?.requests.some((row) => row.makerspace.slug === resolvedSlug && row.state === "requested");
  const profile = useQuery({ queryKey: ["member", "profile"], queryFn: fetchMe, enabled: Boolean(memberships.data), retry: false });
  const invitations = useQuery({ queryKey: ["member", "invitations"], queryFn: () => staffRequest<Invitations>("/memberships/invitations"), enabled: Boolean(memberships.data), retry: false });
  const waiver = useQuery({ queryKey: ["member", resolvedSlug, "waiver"], queryFn: () => staffRequest<Waiver>(`/member/makerspaces/${makerspaceId}/waiver`), enabled: makerspaceId >= 0 && membership?.membership_status === "active", retry: false });
  const presence = useQuery({ queryKey: ["member", resolvedSlug, "presence"], queryFn: () => staffRequest<Presence>(`/public/${resolvedSlug}/presence-sessions/current`), enabled: Boolean(resolvedSlug) && membership?.membership_status === "active", retry: false });
  const activity = useQuery({ queryKey: ["member", resolvedSlug, "activity"], queryFn: () => staffRequest<MemberActivity>(`/member/makerspaces/${makerspaceId}/activity`), enabled: makerspaceId >= 0 && membership?.membership_status === "active", retry: false });
  const payments = useQuery({ queryKey: ["member", resolvedSlug, "payments"], queryFn: () => staffRequest<MemberPayment[]>(`/member/makerspaces/${makerspaceId}/payments`), enabled: makerspaceId >= 0 && membership?.membership_status === "active", retry: false });
  const refresh = () => client.invalidateQueries({ queryKey: ["member"] });
  const request = useMutation({ mutationFn: () => staffRequest<MembershipOutcome>(`/public/${resolvedSlug}/membership-requests`, { method: "POST", body: JSON.stringify({}) }), onSuccess: refresh });
  const accept = useMutation({ mutationFn: () => staffRequest(`/member/makerspaces/${makerspaceId}/waiver/accept`, { method: "POST" }), onSuccess: refresh });
  const start = useMutation({ mutationFn: async () => {
    const location = await presenceStartLocation(Boolean(bootstrap.data?.makerspace.geofence_enabled));
    return staffRequest(`/public/${resolvedSlug}/presence-sessions`, {
      method: "POST",
      body: JSON.stringify({ duration_minutes: 120, ...(location ?? {}) }),
    });
  }, onSuccess: refresh });
  const end = useMutation({ mutationFn: () => staffRequest(`/public/${resolvedSlug}/presence-sessions/current/end`, { method: "POST" }), onSuccess: refresh });
  const refer = useMutation({ mutationFn: (inviteEmail: string) => staffRequest<ReferralOutcome>(`/member/makerspaces/${makerspaceId}/referrals`, { method: "POST", body: JSON.stringify({ invite_email: inviteEmail }) }), onSuccess: refresh });
  const claim = useMutation({ mutationFn: (id: number) => staffRequest<ClaimOutcome>(`/memberships/invitations/${id}/claim`, { method: "POST" }), onSuccess: refresh });
  const generatePaymentLink = useMutation({ mutationFn: (id: number) => staffRequest<{ checkout_url: string }>(`/member/makerspaces/${makerspaceId}/payments/${id}/checkout`, { method: "POST" }), onSuccess: (data) => { refresh(); window.location.assign(data.checkout_url); } });
  const spaceInvitations = invitations.data?.invitations.filter((item) => item.makerspace.slug === resolvedSlug) ?? [];
  const error = bootstrap.error ?? (!unauthenticated ? memberships.error : null) ?? request.error ?? accept.error ?? start.error ?? end.error ?? activity.error ?? generatePaymentLink.error;
  const policy: MembershipPolicyEnum | undefined = bootstrap.data?.makerspace.membership_policy;

  if (restoring) return <main className="desk-shell grid place-items-center px-5 text-sm text-muted">Restoring session…</main>;
  if (showSignIn) return <MemberAuthPanel onAuthenticated={() => { setShowSignIn(false); void client.invalidateQueries({ queryKey: ["member"] }); }} />;

  return <main className="desk-shell mx-auto max-w-3xl space-y-5 px-5 py-8"><header><p className="text-xs font-semibold uppercase tracking-wide text-accent-ink">Member area</p><h1 className="mt-2 text-3xl font-bold text-ink">Your makerspace access</h1></header>
    {bootstrap.isLoading ? <section className="desk-panel p-5 text-sm text-muted">Loading makerspace joining options…</section> : null}
    {bootstrap.isError ? <section className="desk-panel p-5"><p className="text-sm text-danger" role="alert">{message(bootstrap.error)}</p></section> : null}
    {policy && !membership && !requested && memberships.isLoading ? <section className="desk-panel p-5 text-sm text-muted">Checking your sign-in status…</section> : null}
    {policy && !membership && !requested && !memberships.isLoading ? <JoinMembershipCta policy={policy} signedIn={Boolean(memberships.data)} pending={request.isPending} onJoin={() => request.mutate()} onSignIn={() => setShowSignIn(true)} /> : null}
    {requested ? <section className="desk-panel p-5"><h2 className="font-semibold text-ink">Membership request sent</h2><p className="mt-1 text-sm text-muted">Staff will review your request.</p></section> : null}
    {membership ? <><section className="desk-panel p-5"><h2 className="font-semibold text-ink">Membership</h2><p className="mt-1 text-sm text-muted">{membership.makerspace.name} · {membership.membership_status} · {membership.role}</p></section>
      {waiver.data?.has_waiver ? <section className="desk-panel p-5"><h2 className="font-semibold text-ink">Current waiver ({waiver.data.version})</h2><p className="mt-3 whitespace-pre-wrap text-sm text-muted">{waiver.data.body}</p><button className="desk-button-primary mt-4" disabled={accept.isPending} onClick={() => accept.mutate()}>Accept waiver</button></section> : null}
      <section className="desk-panel p-5"><h2 className="font-semibold text-ink">Presence</h2><p className="mt-1 text-sm text-muted">{presence.data?.active ? `Active until ${new Date(presence.data.session?.expires_at ?? "").toLocaleTimeString()}` : "No active session."}</p><button className="desk-button-primary mt-4" disabled={start.isPending || end.isPending || (!presence.data?.active && !bootstrap.data)} onClick={() => presence.data?.active ? end.mutate() : start.mutate()}>{presence.data?.active ? "End presence" : "Start 2-hour presence"}</button></section>
      {activity.data ? <MemberActivityPanel activity={activity.data} makerspaceId={makerspaceId} /> : null}
      {membership.membership_status === "active" && makerspaceId >= 0 ? <><MemberProfilePanel makerspaceId={makerspaceId} /><MemberDirectory makerspaceId={makerspaceId} /></> : null}{payments.data?.length ? <section className="desk-panel p-5"><h2 className="font-semibold text-ink">Payments</h2><ul className="mt-3 space-y-2 text-sm text-muted">{payments.data.map((payment) => <li key={payment.id}><span className="font-medium text-ink">{payment.subject_label}</span> · {payment.status}{payment.checkout_url ? <> · <a className="text-accent-ink underline" href={payment.checkout_url}>Pay now</a></> : payment.status === "pending" ? <> · <button className="text-accent-ink underline" disabled={generatePaymentLink.isPending} onClick={() => generatePaymentLink.mutate(payment.id)}>Generate payment link</button></> : null}</li>)}</ul></section> : null}</> : null}
    {memberships.data && resolvedSlug && makerspaceId >= 0 ? <MemberReferrals
      canRefer={membership?.membership_status === "active" && membership.can_refer}
      referralsEnabled={membership?.membership_status === "active" && membership.referrals_enabled}
      emailVerified={profile.data?.email_verified}
      invitations={spaceInvitations}
      invitationsLoading={invitations.isLoading}
      invitationError={invitations.error instanceof Error ? invitations.error : null}
      onRefer={(email) => refer.mutateAsync(email)}
      onClaim={(id) => claim.mutate(id)}
      isReferring={refer.isPending}
      claimingId={claim.isPending ? claim.variables : null}
      referralError={refer.error instanceof Error ? refer.error : null}
      referralSuccess={refer.data ? "Referral invitation sent." : null}
      claimError={claim.error instanceof Error ? claim.error : null}
      claimSuccess={claim.data ? claim.data.outcome === "active" ? "You are now an active member." : "Your invitation is waiting for manager approval." : null}
    /> : null}
    {unauthenticated && !showSignIn && policy?.startsWith("invite") ? <p className="text-sm text-muted">Sign in to view memberships or claim an invitation.</p> : null}
    {error ? <p className="text-sm text-danger" role="alert">{message(error)}</p> : null}
    {memberships.isError && !unauthenticated ? <Link className="desk-button-primary inline-flex" to="/admin">Sign in</Link> : null}
  </main>;
}
