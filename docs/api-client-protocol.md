# SpaceWorks API client protocol (v1)

> Reference for anyone building a client against a SpaceWorks deployment's protected API
> surface. The rules here are enforced by `apps/inventory/middleware.py` and
> `apps/apiclients/scope_registry.py`; the invariants behind them are under **API client
> scopes and the protected-route registry** in `docs/INVARIANTS.md`.

## What is protected

Only paths under `HMAC_PROTECTED_PATH_PREFIXES` — by default `/api/public/` and
`/api/v1/public/`. Everything else (the staff API under `/api/v1/admin/`, the Telegram
webhook, the Django control plane) is outside this protocol and authenticates by other
means.

## The three credential shapes

| Shape | Headers | Use |
|---|---|---|
| **Signed server client** | `X-Client-Id` + `X-Timestamp` + `X-Signature` (+ optional `X-Nonce`) | Server-to-server. The only shape that earns a rate-limit tier. |
| **Browser client** | `X-Client-Id` + a registered `Origin` | A first-party web frontend. Identified, **not** trusted: both values are public frontend config and forgeable by a non-browser caller, so this shape never elevates rate limits. |
| **Publishable key** | `X-Publishable-Key` | A tenant's public site. Scoped to that makerspace. |

A server client has no browser origin, and none is required of it.

## Canonical signing string

```
message   = METHOD "\n" FULL_PATH "\n" TIMESTAMP [ "\n" NONCE ] "\n" BODY
signature = hex( HMAC-SHA256( client_secret, message ) )
```

- `METHOD` is upper-case; `FULL_PATH` is the path **including** the query string.
- `TIMESTAMP` is integer seconds since the epoch, and must be within
  `HMAC_MAX_CLOCK_SKEW_SECONDS` (default 300) of server time.
- `BODY` is the raw request body, empty for a bodyless request.
- The nonce part is present **only** when `X-Nonce` is sent.

### The nonce slot, and why a body can be refused

Because the nonce part is optional, a nonced request and a nonce-less request whose body is
`NONCE + "\n" + body` produce **identical** bytes — so the same signature would verify for
both readings, and only the nonced reading claims the nonce. A captured request could
otherwise be replayed for the whole skew window. A nonce-less request whose first line is
itself a well-formed nonce followed by a newline is therefore **rejected**. JSON bodies begin
with `{`, so real callers never hit this.

**Protocol v2 (planned)** removes the ambiguity properly by giving the message a fixed part
count — always signing a nonce slot, empty when absent. It is not v1 because it changes the
message for every existing nonce-less client.

### Nonce rules

- Charset `[A-Za-z0-9._~-]`, at most 128 characters.
- The namespace is `(client_id, nonce)`: two different clients may use the same nonce value.
- A nonce is claimed exactly once per request, atomically, **after** the signature verifies.
- Sending `X-Nonce` opts you in to replay protection immediately, whatever
  `APICLIENT_REQUIRE_NONCE` says: a replay is rejected even while enforcement is off.
- Nonces are never cleared by a secret rotation, so a replay stays rejected across one.

## Scopes

Authorization is per route, from a frozen registry keyed on the versioned view name. The
vocabulary is:

`public:read` · `public:write` · `public:*` · `admin:read` · `admin:write` · `admin:*` ·
`reports:read` · `legacy:v1`

Rules that are easy to get wrong:

- **An unregistered route is denied before any wildcard is considered.** `public:*` cannot
  authorize a route the registry does not know, and neither can `legacy:v1`.
- **`legacy:v1` is frozen.** It authorizes exactly the routes it covered at cutover. Routes
  added later are never absorbed into it.
- Tenant staff may grant exactly `public:read` and `public:write`. Public wildcards,
  every admin scope, `reports:read`, and `legacy:v1` require a global superadmin; a
  superadmin acting through membership in a makerspace hidden from global access is
  tenant-limited.
- **A browser client may hold only read/public scopes** (plus `legacy:v1`).
- A client bound to a makerspace may only reach that makerspace's routes; a route that
  addresses no makerspace admits a tenant-bound client only if it explicitly says so.
- A tenant route whose makerspace cannot be resolved is denied — an unresolvable tenant is
  never treated as "no tenant".

## Secret rotation

`POST /api/v1/admin/api-clients/<pk>/rotate-secret` returns a new secret and keeps the
previous one valid for a grace window (24 hours). During it, either secret authenticates;
after it, only the new one does. A second rotation replaces the single retained previous
secret rather than adding to it, so rotating twice inside the window invalidates the oldest
immediately. There is no way for a client to ask for the old secret to be used — switch when
convenient inside the window.

## Enforcement staging

Two settings gate this, and both default to **False**:

- `API_CLIENT_AUTH_REQUIRED` — when False, an unsigned request to a protected path falls
  through as anonymous and DRF authorization still applies. Every request that *would* have
  been rejected is logged once with its route, method, client id and reason, so a deployment
  can see what would break before turning it on.
- `APICLIENT_REQUIRE_NONCE` — when False, a nonce is optional (but honoured if sent).

`manage.py api_client_enforcement_report` lists what stands in the way of flipping them:
clients still on `legacy:v1`, clients with no allowed origins, and clients whose scopes fall
outside the vocabulary.

## Errors

| Status | Body | Meaning |
|---|---|---|
| 401 | `{"detail": "Invalid client signature."}` | Any credential failure: unknown client, bad signature, skew, nonce replay, scope denied, unresolved or mismatched tenant. Deliberately uniform — it does not tell an attacker which check failed. The server log records the specific reason. |
| 429 | throttled | Rate limit for the client's tier. |

A misconfigured deployment fails at startup rather than at runtime: if
`HMAC_PROTECTED_PATH_PREFIXES` is widened to a prefix whose routes are not registered,
`manage.py check` reports it as an error instead of the deployment silently 401-ing that
whole prefix.
