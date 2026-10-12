import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { clearAccessToken, refreshAccessToken, setAccessToken, staffRequest } from "../../lib/api";
import { MfaFlow } from "./MfaFlow";
import type { MfaChallenge } from "./mfaApi";

export function MfaAccountPage() {
  const [ready, setReady] = useState(false);
  const [password, setPassword] = useState("");
  const [challenge, setChallenge] = useState<MfaChallenge>();
  const [codes, setCodes] = useState<string[]>();
  const [notice, setNotice] = useState("");
  useEffect(() => { void refreshAccessToken().then(setReady); }, []);
  const status = useQuery({ queryKey: ["mfa-status"], enabled: ready,
    queryFn: () => staffRequest<{ enabled: boolean; required: boolean }>("/auth/mfa"), retry: false });
  const enroll = useMutation({ mutationFn: () => staffRequest<MfaChallenge>("/auth/mfa", {
    method: "POST", body: JSON.stringify({ password }),
  }), onSuccess: (value) => { clearAccessToken(); setPassword(""); setChallenge(value); } });
  const change = useMutation({ mutationFn: (operation: "recovery" | "disable") => staffRequest<{ recovery_codes?: string[] }>(`/auth/mfa/${operation}`, {
    method: "POST", body: JSON.stringify({ password }),
  }), onSuccess: (value) => { setCodes(value.recovery_codes); setPassword(""); clearAccessToken(); setReady(false); setNotice("Your previous sessions have ended. Sign in again to continue."); } });
  if (challenge) return <main className="desk-shell p-6"><MfaFlow challenge={challenge} onCancel={() => { setChallenge(undefined); setReady(false); }}
    onComplete={(result) => { setAccessToken(result.access); setChallenge(undefined); setReady(true); void status.refetch(); }} /></main>;
  return <main className="desk-shell p-6"><section className="desk-panel mx-auto grid max-w-lg gap-4 p-6">
    <h1 className="text-2xl font-bold">Two-step sign-in</h1>
    {!ready ? <p>{notice || "Sign in to manage your authenticator."}</p> : <>
      <p>{status.data?.enabled ? "Your authenticator is enrolled." : "Add an authenticator to protect your account."}{status.data?.required ? " MFA is required for this account." : ""}</p>
      <label htmlFor="mfa-password">Confirm your current password</label>
      <input id="mfa-password" className="desk-input" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
      {status.data?.enabled ? <>
        <button className="desk-button" disabled={!password || change.isPending} onClick={() => change.mutate("recovery")}>Regenerate recovery codes</button>
        {!status.data.required ? <button className="desk-button" disabled={!password || change.isPending} onClick={() => change.mutate("disable")}>Disable MFA</button> : null}
      </> : <button className="desk-button-primary" disabled={!password || enroll.isPending || status.isLoading} onClick={() => enroll.mutate()}>Enroll authenticator</button>}
    </>}
    {codes ? <><p>Save these one-time codes now:</p><ul>{codes.map((code) => <li key={code}><code>{code}</code></li>)}</ul></> : null}
    {status.error || enroll.error || change.error ? <p role="alert" className="text-danger">{(status.error ?? enroll.error ?? change.error)?.message}</p> : null}
    <Link to="/admin" className="desk-link">Staff sign-in</Link><Link to="/member" className="desk-link">Member sign-in</Link>
  </section></main>;
}
