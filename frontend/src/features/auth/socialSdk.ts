import { publicV1Request } from "../../lib/api";

export type SocialProvider = "google" | "apple";
export type SocialSurface = "member" | "staff";
export type SocialLoginResult = {
  access: string;
  user: Record<string, unknown>;
  outcome: "created" | "existing" | "auto_linked";
};
export type SocialConfig = {
  google?: { enabled: boolean; web_client_id: string };
  apple?: { enabled: boolean; service_id: string };
  [provider: `oidc:${string}`]:
    | { enabled: boolean; display_name: string; client_id: string; issuer: string }
    | undefined;
};

type OidcStartResult = {
  authorization_url: string;
  state: string;
  nonce: string;
};

const OIDC_NONCE_PREFIX = "spaceworks.oidc.nonce.";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(options: Record<string, unknown>): void;
          renderButton(element: HTMLElement, options: Record<string, unknown>): void;
        };
      };
    };
    AppleID?: {
      auth: {
        init(options: Record<string, unknown>): void;
        signIn(): Promise<{ authorization: { id_token: string }; user?: { name?: { firstName?: string; lastName?: string } } }>;
      };
    };
  }
}

const scripts = new Map<string, Promise<void>>();

function loadScript(src: string) {
  const existing = scripts.get(src);
  if (existing) return existing;
  const pending = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Unable to load the identity provider."));
    document.head.appendChild(script);
  });
  scripts.set(src, pending);
  return pending;
}

async function requestNonce(provider: SocialProvider, surface: SocialSurface) {
  return publicV1Request<{ nonce: string }>("/auth/social/nonce", {
    method: "POST",
    body: JSON.stringify({
      provider,
      surface,
      delivery: "web",
      client_platform: "web",
    }),
  });
}

async function complete(provider: SocialProvider, surface: SocialSurface, idToken: string, nonce: string, appleName = "") {
  return publicV1Request<SocialLoginResult>(`/auth/social/${provider}`, {
    method: "POST",
    credentials: "include",
    body: JSON.stringify({
      id_token: idToken,
      nonce,
      surface,
      delivery: "web",
      client_platform: "web",
      ...(appleName ? { apple_name: appleName } : {}),
    }),
  });
}

export async function mountGoogleButton(
  element: HTMLElement,
  clientId: string,
  surface: SocialSurface,
  onSuccess: (result: SocialLoginResult) => void,
  onError: (error: Error) => void,
) {
  const { nonce } = await requestNonce("google", surface);
  await loadScript("https://accounts.google.com/gsi/client");
  if (!window.google) throw new Error("Google sign-in is unavailable.");
  window.google.accounts.id.initialize({
    client_id: clientId,
    nonce,
    callback: async ({ credential }: { credential?: string }) => {
      if (!credential) return onError(new Error("Google sign-in was cancelled."));
      try {
        onSuccess(await complete("google", surface, credential, nonce));
      } catch (error) {
        onError(error instanceof Error ? error : new Error("Google sign-in failed."));
      }
    },
  });
  window.google.accounts.id.renderButton(element, {
    type: "standard",
    theme: "outline",
    size: "large",
    width: Math.min(360, Math.max(240, element.clientWidth || 320)),
  });
}

export async function signInWithApple(serviceId: string, surface: SocialSurface) {
  const { nonce } = await requestNonce("apple", surface);
  await loadScript("https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js");
  if (!window.AppleID) throw new Error("Apple sign-in is unavailable.");
  window.AppleID.auth.init({
    clientId: serviceId,
    scope: "name email",
    redirectURI: window.location.origin,
    usePopup: true,
    nonce,
  });
  const result = await window.AppleID.auth.signIn();
  const name = [result.user?.name?.firstName, result.user?.name?.lastName].filter(Boolean).join(" ");
  return complete("apple", surface, result.authorization.id_token, nonce, name);
}

export async function beginOidcBrowser(
  slug: string,
  email: string,
  makerspaceSlug: string,
) {
  const redirectUri = `${window.location.origin}${window.location.pathname}`;
  const started = await publicV1Request<OidcStartResult>(
    `/auth/social/oidc/${encodeURIComponent(slug)}/authorize`,
    {
      method: "POST",
      body: JSON.stringify({
        redirect_uri: redirectUri,
        ...(email.trim() ? { email: email.trim() } : {}),
        ...(makerspaceSlug ? { makerspace_slug: makerspaceSlug } : {}),
      }),
    },
  );
  try {
    window.sessionStorage.setItem(`${OIDC_NONCE_PREFIX}${started.state}`, started.nonce);
  } catch {
    throw new Error("Browser storage is required for secure identity-provider sign-in.");
  }
  window.location.assign(started.authorization_url);
}

export async function completeOidcBrowserCallback(): Promise<SocialLoginResult | null> {
  const query = new URLSearchParams(window.location.search);
  const code = query.get("code")?.trim() ?? "";
  const state = query.get("state")?.trim() ?? "";
  if (!code && !state && !query.get("error")) return null;
  if (!code || !state || query.get("error")) {
    clearOidcQuery();
    throw new Error("Identity-provider sign-in was cancelled or refused.");
  }
  let nonce = "";
  try {
    nonce = window.sessionStorage.getItem(`${OIDC_NONCE_PREFIX}${state}`) ?? "";
    window.sessionStorage.removeItem(`${OIDC_NONCE_PREFIX}${state}`);
  } catch {
    // The backend still refuses the callback because the nonce is mandatory.
  }
  clearOidcQuery();
  if (!nonce) throw new Error("Identity-provider sign-in expired. Please try again.");
  return publicV1Request<SocialLoginResult>("/auth/social/oidc/callback", {
    method: "POST",
    credentials: "include",
    body: JSON.stringify({ code, state, nonce }),
  });
}

function clearOidcQuery() {
  const url = new URL(window.location.href);
  for (const key of ["code", "state", "session_state", "iss", "error", "error_description"]) {
    url.searchParams.delete(key);
  }
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}
