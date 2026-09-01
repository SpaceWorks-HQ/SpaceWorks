import { useEffect, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { EmptyState, Skeleton } from "../../components/ui";
import {
  fetchMe,
  refreshAccessToken,
  setAccessToken,
  staffRequest,
  type PasswordLoginResponse,
  type StaffAuthUser,
} from "../../lib/api";

type RedeemResponse = {
  membership: { id: number; organization_id?: number };
  user: StaffAuthUser;
};

export function OrganizationInvitationRedeemPage() {
  const { token = "" } = useParams();
  const [user, setUser] = useState<StaffAuthUser | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [credentials, setCredentials] = useState({ username: "", password: "" });
  const redeem = useMutation({
    mutationFn: () => staffRequest<RedeemResponse>("/auth/organization-invitations/redeem/", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  });
  const login = useMutation({
    mutationFn: () => staffRequest<PasswordLoginResponse<StaffAuthUser>>("/auth/login", {
      method: "POST",
      credentials: "include",
      body: JSON.stringify({ ...credentials, surface: "member" }),
    }),
    onSuccess: (response) => {
      setAccessToken(response.access);
      setUser(response.user);
    },
  });

  useEffect(() => {
    let active = true;
    refreshAccessToken()
      .then((refreshed) => refreshed ? fetchMe() : null)
      .then((current) => { if (active && current) setUser(current); })
      .finally(() => { if (active) setRestoring(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (user && token && !redeem.isPending && !redeem.isSuccess && !redeem.isError) {
      redeem.mutate();
    }
  }, [user, token, redeem]);

  function submit(event: FormEvent) {
    event.preventDefault();
    login.mutate();
  }

  return (
    <main className="desk-shell grid min-h-screen place-items-center px-5 py-10">
      <section className="desk-panel w-full max-w-lg p-6" aria-labelledby="invitation-heading">
        <SpaceWorksBadge className="mb-5" />
        <p className="eyebrow text-secondary-ink">Organization invitation</p>
        <h1 className="title-page mt-2" id="invitation-heading">Join an organization</h1>
        {restoring ? <Skeleton className="mt-5 h-32 w-full" /> : null}
        {!restoring && !user ? (
          <form className="mt-5 grid gap-3" onSubmit={submit}>
            <p className="text-sm text-muted">Sign in to bind this single-use invitation to your account.</p>
            <label className="grid gap-1 text-sm font-semibold">Username or email<input className="desk-input" autoComplete="username" required value={credentials.username} onChange={(event) => setCredentials({ ...credentials, username: event.target.value })} /></label>
            <label className="grid gap-1 text-sm font-semibold">Password<input className="desk-input" type="password" autoComplete="current-password" required value={credentials.password} onChange={(event) => setCredentials({ ...credentials, password: event.target.value })} /></label>
            <button className="desk-button-primary" type="submit" disabled={login.isPending}>{login.isPending ? "Signing in..." : "Sign in and continue"}</button>
            {login.error ? <p className="text-sm text-danger" role="alert">{login.error.message}</p> : null}
          </form>
        ) : null}
        {user && redeem.isPending ? <p className="mt-5 text-sm text-muted">Redeeming invitation...</p> : null}
        {redeem.isSuccess ? (
          <div className="mt-5 rounded-xl border border-success bg-success/15 p-4 text-success-ink" role="status">
            <h2 className="title-section">Invitation redeemed</h2>
            <p className="mt-2 text-sm">Your organization access is active. Makerspace actions remain scoped to the organization's linked makerspaces.</p>
            <Link className="desk-button-primary mt-4" to="/admin/organizations">Open organizations</Link>
          </div>
        ) : null}
        {redeem.isError ? <EmptyState title="Invitation unavailable" description={redeem.error.message} action={<Link className="desk-button" to="/">Return to directory</Link>} /> : null}
      </section>
    </main>
  );
}
