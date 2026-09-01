import { useEffect, useState } from "react";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import {
  publicV1Request,
  setAccessToken,
  staffRequest,
  type PasswordLoginRequest,
  type PasswordLoginResponse,
} from "../../lib/api";
import { SocialSignInButtons } from "../auth/SocialSignInButtons";

export function MemberAuthPanel({
  onAuthenticated,
  makerspaceSlug = "",
}: {
  onAuthenticated: () => void;
  makerspaceSlug?: string;
}) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [verificationOnly, setVerificationOnly] = useState(false);
  const [verificationCode, setVerificationCode] = useState("");
  // Each of these appears in the public config only when it has been switched off, so
  // an absent key — and a failed request — mean available.
  const [selfServeAccounts, setSelfServeAccounts] = useState(true);
  const [passwordLogin, setPasswordLogin] = useState(true);

  useEffect(() => {
    publicV1Request<{
      member_accounts?: { enabled: boolean };
      self_registration?: { enabled: boolean };
      password_login?: { enabled: boolean };
    }>("/config")
      .then((result) => {
        setSelfServeAccounts(
          result.member_accounts?.enabled !== false &&
            result.self_registration?.enabled !== false,
        );
        setPasswordLogin(result.password_login?.enabled !== false);
      })
      .catch(() => {
        setSelfServeAccounts(true);
        setPasswordLogin(true);
      });
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
        const request = {
          username: email,
          password,
          surface: "member",
        } satisfies PasswordLoginRequest;
        const result = await publicV1Request<PasswordLoginResponse>("/auth/login", {
          method: "POST",
          credentials: "include",
          body: JSON.stringify(request),
        });
        setAccessToken(result.access);
        if (result.surface === "verification_only") {
          setVerificationOnly(true);
          setNotice("Enter the verification code sent to your email.");
        } else {
          onAuthenticated();
        }
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to continue.");
    } finally {
      setPending(false);
    }
  };

  const confirmVerification = async () => {
    setPending(true);
    setError("");
    try {
      await staffRequest("/auth/email-verification/confirm", {
        method: "POST",
        body: JSON.stringify({ code: verificationCode }),
      });
      onAuthenticated();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to verify email.");
    } finally {
      setPending(false);
    }
  };

  const resendVerification = async () => {
    setPending(true);
    setError("");
    try {
      await staffRequest("/auth/email-verification/resend", { method: "POST" });
      setNotice("If the details are valid, a verification email has been sent.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to resend the code.");
    } finally {
      setPending(false);
    }
  };

  if (verificationOnly) {
    return (
      <main className="desk-shell grid place-items-center px-5 py-8">
        <form
          className="desk-panel w-full max-w-md p-6"
          onSubmit={(event) => { event.preventDefault(); void confirmVerification(); }}
        >
          <SpaceWorksBadge className="mb-5" />
          <h1 className="title-page">Verify your email</h1>
          <p className="mt-2 text-sm text-muted">
            This session can only verify the address until email ownership is confirmed.
          </p>
          <label className="eyebrow mt-5 block" htmlFor="member-verification-code">Verification code</label>
          <input
            id="member-verification-code"
            className="desk-input mt-1 w-full"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={verificationCode}
            onChange={(event) => setVerificationCode(event.target.value)}
            required
          />
          {notice ? <p className="mt-3 text-sm text-success-ink">{notice}</p> : null}
          {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
          <button className="desk-button-secondary mt-5 w-full" type="submit" disabled={pending}>
            {pending ? "Please wait…" : "Verify email"}
          </button>
          <button
            className="desk-button-ghost mt-3 w-full"
            type="button"
            disabled={pending}
            onClick={() => { void resendVerification(); }}
          >
            Resend code
          </button>
        </form>
      </main>
    );
  }

  return (
    <main className="desk-shell grid place-items-center px-5 py-8">
      <form
        className="desk-panel w-full max-w-md p-6"
        onSubmit={(event) => { event.preventDefault(); void submit(); }}
      >
        <SpaceWorksBadge className="mb-5" />
        <h1 className="title-page">
          {mode === "login" ? "Member sign in" : "Create a member account"}
        </h1>
        <p className="mt-2 text-sm text-muted">
          {mode === "signup"
            ? "Use one global account across every makerspace you join."
            : passwordLogin
              ? "Sign in to manage memberships, waivers, visits, and payments."
              : "This space signs members in through an identity provider."}
        </p>
        {mode === "signup" ? (
          <>
            <label className="eyebrow mt-5 block" htmlFor="member-name">Name</label>
            <input id="member-name" className="desk-input mt-1 w-full" autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
            <label className="eyebrow mt-3 block" htmlFor="member-phone">Phone <span className="normal-case tracking-normal text-muted">(optional)</span></label>
            <input id="member-phone" className="desk-input mt-1 w-full" autoComplete="tel" value={phone} onChange={(event) => setPhone(event.target.value)} />
          </>
        ) : null}
        {/* Sign-up still needs both fields: it sets the password it cannot be used with
            yet, so the account stays recoverable if the switch is ever turned back on. */}
        {passwordLogin || mode === "signup" ? (
          <>
            <label className={`${mode === "login" ? "mt-5" : "mt-3"} eyebrow block`} htmlFor="member-email">Email</label>
            <input id="member-email" className="desk-input mt-1 w-full" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
            <label className="eyebrow mt-3 block" htmlFor="member-password">Password</label>
            <input id="member-password" className="desk-input mt-1 w-full" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} required />
          </>
        ) : (
          <>
            <label className="eyebrow mt-5 block" htmlFor="member-email">Email</label>
            <input id="member-email" className="desk-input mt-1 w-full" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </>
        )}
        {notice ? <p className="mt-3 text-sm text-success-ink">{notice}</p> : null}
        {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
        {passwordLogin || mode === "signup" ? (
          <button className="desk-button-secondary mt-5 w-full" type="submit" disabled={pending}>
            {pending ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        ) : null}
        {selfServeAccounts ? (
          <button className="desk-button-ghost mt-3 w-full" type="button" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }}>
            {mode === "login" ? "Create a member account" : "Back to sign in"}
          </button>
        ) : (
          <p className="mt-3 text-center text-sm text-muted">
            This space does not run self sign-up. Ask a staff member to add you.
          </p>
        )}
        <SocialSignInButtons
          surface="member"
          email={email}
          makerspaceSlug={makerspaceSlug}
          onSuccess={(result) => {
            setAccessToken(result.access);
            onAuthenticated();
          }}
        />
      </form>
    </main>
  );
}
