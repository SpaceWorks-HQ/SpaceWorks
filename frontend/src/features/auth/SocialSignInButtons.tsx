import { useEffect, useRef, useState } from "react";

import { publicV1Request } from "../../lib/api";
import {
  beginOidcBrowser,
  completeOidcBrowserCallback,
  mountGoogleButton,
  signInWithApple,
  type SocialConfig,
  type SocialLoginResult,
  type SocialSurface,
} from "./socialSdk";

export function SocialSignInButtons({
  surface,
  onSuccess,
  email = "",
  makerspaceSlug = "",
}: {
  surface: SocialSurface;
  onSuccess: (result: SocialLoginResult) => void;
  email?: string;
  makerspaceSlug?: string;
}) {
  const googleHost = useRef<HTMLDivElement>(null);
  const onSuccessRef = useRef(onSuccess);
  const [config, setConfig] = useState<SocialConfig>();
  const [memberAccounts, setMemberAccounts] = useState(true);
  const [error, setError] = useState("");
  const [applePending, setApplePending] = useState(false);
  const [oidcPending, setOidcPending] = useState("");
  const callbackHandled = useRef(false);

  useEffect(() => {
    onSuccessRef.current = onSuccess;
  }, [onSuccess]);

  useEffect(() => {
    publicV1Request<{ social_auth?: SocialConfig; member_accounts?: { enabled: boolean } }>(
      "/config",
    )
      .then((result) => {
        setConfig(result.social_auth ?? {});
        // Present only when member accounts are switched off, so an absent key means
        // on — which is also what a failed request falls back to.
        setMemberAccounts(result.member_accounts?.enabled !== false);
      })
      .catch(() => setConfig({}));
  }, []);

  useEffect(() => {
    if (surface !== "member" || callbackHandled.current) return;
    callbackHandled.current = true;
    void completeOidcBrowserCallback()
      .then((result) => {
        if (result) onSuccessRef.current(result);
      })
      .catch((nextError: unknown) => {
        setError(nextError instanceof Error ? nextError.message : "Identity-provider sign-in failed.");
      });
  }, [surface]);

  useEffect(() => {
    const host = googleHost.current;
    if (!host || !config?.google?.enabled) return;
    host.replaceChildren();
    void mountGoogleButton(
      host,
      config.google.web_client_id,
      surface,
      (result) => onSuccessRef.current(result),
      (nextError) => setError(nextError.message),
    ).catch((nextError: unknown) => {
      setError(nextError instanceof Error ? nextError.message : "Google sign-in failed.");
    });
  }, [config, surface]);

  const oidcProviders = surface === "member"
    ? Object.entries(config ?? {}).filter(
        (entry): entry is [string, NonNullable<SocialConfig[`oidc:${string}`]>] =>
          entry[0].startsWith("oidc:") && Boolean(entry[1]?.enabled),
      )
    : [];
  // Accounts-off hides only the built-in consumer ecosystem. Institution-owned OIDC
  // is the member login path that must remain available; staff still keep the built-ins.
  const showBuiltins = surface === "staff" || memberAccounts;
  const showGoogle = showBuiltins && Boolean(config?.google?.enabled);
  const showApple = showBuiltins && Boolean(config?.apple?.enabled);
  if (!showGoogle && !showApple && oidcProviders.length === 0) return null;

  return (
    <section className="mt-5 border-t border-line pt-5" aria-label="Social sign in">
      <p className="eyebrow mb-3 text-center">Or continue with</p>
      <div className="flex flex-col items-center gap-3">
        {showGoogle ? <div ref={googleHost} className="min-h-10 w-full text-center" /> : null}
        {showApple ? (
          <button
            className="desk-button-secondary w-full max-w-[360px]"
            type="button"
            disabled={applePending}
            onClick={async () => {
              setApplePending(true);
              setError("");
              try {
                onSuccessRef.current(await signInWithApple(config?.apple?.service_id ?? "", surface));
              } catch (nextError) {
                setError(nextError instanceof Error ? nextError.message : "Apple sign-in failed.");
              } finally {
                setApplePending(false);
              }
            }}
          >
            {applePending ? "Connecting to Apple…" : "Continue with Apple"}
          </button>
        ) : null}
        {oidcProviders.map(([key, provider]) => {
          const slug = key.slice("oidc:".length);
          return (
            <button
              key={key}
              className="desk-button-secondary w-full max-w-[360px]"
              type="button"
              disabled={Boolean(oidcPending)}
              onClick={async () => {
                setOidcPending(key);
                setError("");
                try {
                  await beginOidcBrowser(slug, email, makerspaceSlug);
                } catch (nextError) {
                  setOidcPending("");
                  setError(nextError instanceof Error ? nextError.message : "Identity-provider sign-in failed.");
                }
              }}
            >
              {oidcPending === key
                ? `Connecting to ${provider.display_name}…`
                : `Continue with ${provider.display_name}`}
            </button>
          );
        })}
      </div>
      {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
    </section>
  );
}
