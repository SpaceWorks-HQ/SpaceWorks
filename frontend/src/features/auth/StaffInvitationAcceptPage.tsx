import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";

import { mfaRequest } from "./mfaApi";

export function StaffInvitationAcceptPage() {
  const [link] = useState(() => new URLSearchParams(window.location.hash.slice(1)));
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const accept = useMutation({ mutationFn: () => mfaRequest<{ detail: string }>("/auth/staff-invitations/accept", {
    token: link.get("token"), makerspace_slug: link.get("space"), password, code,
  }), onSuccess: () => { setPassword(""); setCode(""); window.history.replaceState(null, "", window.location.pathname); } });
  return <main className="desk-shell p-6"><section className="desk-panel mx-auto grid max-w-lg gap-4 p-6">
    <h1 className="text-2xl font-bold">Accept your staff invitation</h1>
    {accept.data ? <><p role="status">{accept.data.detail}</p><Link to="/admin" className="desk-link">Sign in with your email</Link></> : <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); accept.mutate(); }}>
      <p>Already have an account? Use its current password. Otherwise, choose a strong password for your new account.</p>
      <label htmlFor="invite-password">Password</label>
      <input id="invite-password" className="desk-input" type="password" autoComplete="current-password" value={password} required onChange={(event) => setPassword(event.target.value)} />
      <label htmlFor="invite-code">Authenticator or recovery code (if your account has MFA)</label>
      <input id="invite-code" className="desk-input" autoComplete="one-time-code" value={code} maxLength={64} onChange={(event) => setCode(event.target.value)} />
      <button className="desk-button-primary" disabled={accept.isPending || !link.get("token")}>Accept invitation</button>
      {accept.error ? <p role="alert" className="text-danger">{accept.error.message}</p> : null}
    </form>}
  </section></main>;
}
