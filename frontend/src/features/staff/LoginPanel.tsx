import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { publicV1Request } from "../../lib/api";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { SocialSignInButtons } from "../auth/SocialSignInButtons";
import type { SocialLoginResult } from "../auth/socialSdk";

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
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [emailEnabled, setEmailEnabled] = useState(false);
  // Present in the config only when password sign-in has been switched off, so an
  // absent key — and a failed request — mean it is available.
  const [passwordLogin, setPasswordLogin] = useState(true);

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
            <label className="mt-5 block text-sm font-semibold" htmlFor="staff-username">
              Username
            </label>
            <input
              id="staff-username"
              className="desk-input mt-1 w-full"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <label className="mt-3 block text-sm font-semibold" htmlFor="staff-password">
              Password
            </label>
            <input
              id="staff-password"
              className="desk-input mt-1 w-full"
              name="password"
              autoComplete="current-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </>
        ) : null}
        {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
        {passwordLogin ? (
          <button
            className="desk-button-secondary mt-5 w-full"
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
          <Link
            className="desk-button-ghost mt-3 w-full"
            to="/reset-password"
          >
            Forgot password?
          </Link>
        ) : null}
        {onSocialSuccess ? (
          <SocialSignInButtons surface="staff" onSuccess={onSocialSuccess} />
        ) : null}
      </form>
    </main>
  );
}
