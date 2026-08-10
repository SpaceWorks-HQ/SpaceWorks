import { useEffect, useState } from "react";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { publicV1Request, setAccessToken } from "../../lib/api";
import { SocialSignInButtons } from "../auth/SocialSignInButtons";

export function MemberAuthPanel({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // `member_accounts` appears in the public config only when the deployment has
  // switched member accounts off, so an absent key — and a failed request — mean on.
  const [selfServeAccounts, setSelfServeAccounts] = useState(true);

  useEffect(() => {
    publicV1Request<{ member_accounts?: { enabled: boolean } }>("/config")
      .then((result) => setSelfServeAccounts(result.member_accounts?.enabled !== false))
      .catch(() => setSelfServeAccounts(true));
  }, []);

  useEffect(() => {
    if (!selfServeAccounts) setMode("login");
  }, [selfServeAccounts]);

  const submit = async () => {
    setPending(true);
    setError("");
    setNotice("");
    try {
      if (mode === "signup") {
        await publicV1Request("/auth/member-sign-up", {
          method: "POST",
          body: JSON.stringify({ display_name: displayName, email, phone, password, website: "" }),
        });
        setMode("login");
        setNotice("Check your email to verify the new account, then sign in.");
      } else {
        const result = await publicV1Request<{ access: string }>("/auth/login", {
          method: "POST",
          credentials: "include",
          body: JSON.stringify({ username: email, password }),
        });
        setAccessToken(result.access);
        onAuthenticated();
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to continue.");
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="desk-shell grid place-items-center px-5 py-8">
      <form
        className="desk-panel w-full max-w-md p-6"
        onSubmit={(event) => { event.preventDefault(); void submit(); }}
      >
        <SpaceWorksBadge className="mb-5" />
        <h1 className="text-2xl font-bold text-ink">
          {mode === "login" ? "Member sign in" : "Create a member account"}
        </h1>
        <p className="mt-2 text-sm text-muted">
          {mode === "login"
            ? "Sign in to manage memberships, waivers, visits, and payments."
            : "Use one global account across every makerspace you join."}
        </p>
        {mode === "signup" ? (
          <>
            <label className="mt-5 block text-sm font-semibold" htmlFor="member-name">Name</label>
            <input id="member-name" className="desk-input mt-1 w-full" autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
            <label className="mt-3 block text-sm font-semibold" htmlFor="member-phone">Phone <span className="font-normal text-muted">(optional)</span></label>
            <input id="member-phone" className="desk-input mt-1 w-full" autoComplete="tel" value={phone} onChange={(event) => setPhone(event.target.value)} />
          </>
        ) : null}
        <label className={`${mode === "login" ? "mt-5" : "mt-3"} block text-sm font-semibold`} htmlFor="member-email">Email</label>
        <input id="member-email" className="desk-input mt-1 w-full" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        <label className="mt-3 block text-sm font-semibold" htmlFor="member-password">Password</label>
        <input id="member-password" className="desk-input mt-1 w-full" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} required />
        {notice ? <p className="mt-3 text-sm text-success-ink">{notice}</p> : null}
        {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
        <button className="desk-button-primary mt-5 w-full" type="submit" disabled={pending}>
          {pending ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
        {selfServeAccounts ? (
          <button className="mt-3 w-full text-sm font-semibold text-accent-ink" type="button" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }}>
            {mode === "login" ? "Create a member account" : "Back to sign in"}
          </button>
        ) : (
          <p className="mt-3 text-center text-sm text-muted">
            This space does not run self sign-up. Ask a staff member to add you.
          </p>
        )}
        <SocialSignInButtons
          surface="member"
          onSuccess={(result) => {
            setAccessToken(result.access);
            onAuthenticated();
          }}
        />
      </form>
    </main>
  );
}
