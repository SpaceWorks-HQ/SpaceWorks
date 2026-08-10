import { useEffect, useState } from "react";

import { publicV1Request } from "../../lib/api";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { SocialSignInButtons } from "../auth/SocialSignInButtons";
import type { SocialLoginResult } from "../auth/socialSdk";

const RESET_SENT_MESSAGE =
  "If an account exists for that email, a reset link has been sent. Check your inbox.";

export function LoginPanel({
  error,
  guestOnly,
  isPending,
  onSubmit,
  onSocialSuccess,
}: {
  error?: string;
  guestOnly: boolean;
  isPending: boolean;
  onSubmit: (payload: { username: string; password: string }) => void;
  onSocialSuccess?: (result: SocialLoginResult) => void;
}) {
  const [mode, setMode] = useState<"login" | "forgot">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [emailEnabled, setEmailEnabled] = useState(false);
  // Present in the config only when password sign-in has been switched off, so an
  // absent key — and a failed request — mean it is available.
  const [passwordLogin, setPasswordLogin] = useState(true);
  const [forgotPending, setForgotPending] = useState(false);
  const [forgotMessage, setForgotMessage] = useState("");

  useEffect(() => {
    let active = true;
    publicV1Request<{ email_enabled: boolean; password_login?: { enabled: boolean } }>(
      "/config",
    )
      .then((config) => {
        if (active) {
          setEmailEnabled(config.email_enabled === true);
          setPasswordLogin(config.password_login?.enabled !== false);
        }
      })
      .catch(() => {
        if (active) {
          setEmailEnabled(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  if (mode === "forgot") {
    return (
      <main className="desk-shell grid place-items-center px-5">
        <form
          className="desk-panel w-full max-w-md p-6"
          onSubmit={async (event) => {
            event.preventDefault();
            setForgotPending(true);
            setForgotMessage("");
            try {
              await publicV1Request("/auth/forgot-password", {
                method: "POST",
                body: JSON.stringify({ email }),
              });
            } catch {
              // Keep the forgot-password flow enumeration-safe even if the
              // endpoint or network fails unexpectedly.
            } finally {
              setForgotMessage(RESET_SENT_MESSAGE);
              setForgotPending(false);
            }
          }}
        >
          <SpaceWorksBadge className="mb-5" />
          <p className="text-xs font-semibold tracking-wide text-accent-ink">
            Account access
          </p>
          <h1 className="mt-2 text-2xl font-bold text-ink">Reset password</h1>
          <p className="mt-2 text-sm text-muted">
            Enter your staff email and we will send a reset link if the account exists.
          </p>
          <label className="mt-5 block text-sm font-semibold">Email</label>
          <input
            className="desk-input mt-1 w-full"
            name="email"
            autoComplete="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          {forgotMessage ? <p className="mt-3 text-sm text-muted">{forgotMessage}</p> : null}
          <button
            className="desk-button-primary mt-5 flex w-full items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
            type="submit"
            disabled={forgotPending}
          >
            {forgotPending ? (
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-bg/40 border-t-bg" />
            ) : null}
            {forgotPending ? "Sending..." : "Send reset link"}
          </button>
          <button
            className="mt-3 w-full text-sm font-semibold text-accent-ink hover:text-accent-ink/80"
            type="button"
            onClick={() => setMode("login")}
          >
            Back to sign in
          </button>
        </form>
      </main>
    );
  }

  return (
    <main className="desk-shell grid place-items-center px-5">
      <form
        className="desk-panel w-full max-w-md p-6"
        onSubmit={(event) => {
          event.preventDefault();
          if (isPending) return;
          onSubmit({ username, password });
        }}
      >
        <SpaceWorksBadge className="mb-5" />
        <p className="text-xs font-semibold tracking-wide text-accent-ink">
          {guestOnly ? "Guest admin desk" : "Space Manager desk"}
        </p>
        <h1 className="mt-2 text-2xl font-bold text-ink">Sign in</h1>
        <p className="mt-2 text-sm text-muted">
          {passwordLogin
            ? "Use your staff account to manage requests, inventory, and handovers."
            : "This deployment signs staff in through an identity provider."}
        </p>
        {passwordLogin ? (
          <>
            <label className="mt-5 block text-sm font-semibold">Username</label>
            <input
              className="desk-input mt-1 w-full"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <label className="mt-3 block text-sm font-semibold">Password</label>
            <input
              className="desk-input mt-1 w-full"
              name="password"
              autoComplete="current-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </>
        ) : null}
        {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}
        {passwordLogin ? (
          <button
            className="desk-button-primary mt-5 flex w-full items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
            type="submit"
            disabled={isPending}
          >
            {isPending ? (
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-bg/40 border-t-bg" />
            ) : null}
            {isPending ? "Signing in..." : "Sign in"}
          </button>
        ) : null}
        {emailEnabled && passwordLogin ? (
          <button
            className="mt-3 w-full text-sm font-semibold text-accent-ink hover:text-accent-ink/80"
            type="button"
            onClick={() => setMode("forgot")}
          >
            Forgot password?
          </button>
        ) : null}
        {onSocialSuccess ? (
          <SocialSignInButtons surface="staff" onSuccess={onSocialSuccess} />
        ) : null}
      </form>
    </main>
  );
}
