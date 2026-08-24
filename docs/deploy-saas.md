# SaaS deployment on `space-works.tech`

This runbook deploys one Space Works application stack behind Caddy, with Cloudflare-fronted platform
subdomains and Caddy on-demand TLS for verified tenant custom domains. Run commands from the
repository root on the VPS.

## 1. VPS prerequisites

- Install Docker Engine with the Docker Compose plugin.
- Point a stable public IPv4 address at the VPS.
- Allow inbound TCP 80 and TCP/UDP 443 in both the provider firewall and the host firewall.
- Keep the database, Redis, MinIO, and backend ports closed to the public internet. The SaaS
  Compose overlay publishes only Caddy.
- Create the certificate directory with restrictive ownership: `mkdir -p deploy/certs`.

## 2. Cloudflare setup

Add the `space-works.tech` zone to Cloudflare and update the registrar nameservers. Create these records,
replacing `VPS_IP` with the server address:

| Type | Name | Target | Proxy |
| --- | --- | --- | --- |
| A | `space-works.tech` | `VPS_IP` | Proxied |
| A | `origin.space-works.tech` | `VPS_IP` | DNS only |
| CNAME | `files.space-works.tech` | `space-works.tech` | Proxied |
| A | `*.space-works.tech` | `VPS_IP` | Proxied |

`origin.space-works.tech` must be DNS-only when arbitrary tenant domains CNAME to it. Otherwise Cloudflare
would receive the tenant hostname instead of sending it to this Caddy instance for on-demand TLS.
The apex, wildcard, and files host can remain proxied.

In **SSL/TLS**, select **Full (strict)**. Create a Cloudflare Origin CA certificate covering
`space-works.tech` and `*.space-works.tech`, then place the PEM files on the VPS at:

```text
deploy/certs/spaceworks.crt
deploy/certs/spaceworks.key
```

Restrict the private key, for example with `chmod 600 deploy/certs/spaceworks.key`. Never commit either
file. Cloudflare Origin CA certificates are trusted between Cloudflare and the origin; they are not
general-purpose browser certificates.

## 3. Deploy and initialize

Populate `.env` with the required production secrets described in [Self-hosting](self-hosting.md).
In particular, set strong `SECRET_KEY`, `POSTGRES_PASSWORD`, `MINIO_ROOT_USER`, and
`MINIO_ROOT_PASSWORD` values. `ALLOWED_HOSTS` is still required by the base Compose interpolation;
the trusted-proxy host middleware becomes the effective host boundary in SaaS mode.

Start the layered stack:

```bash
SPACEWORKS_COMPOSE_LAYER=saas scripts/spaceworks-compose.sh bundled up -d
```

Create the first superadmin and makerspace with an explicit strong password:

```bash
SPACEWORKS_COMPOSE_LAYER=saas scripts/spaceworks-compose.sh bundled \
  run --rm --no-deps backend --role management python manage.py setup_instance \
  --username admin \
  --email admin@space-works.tech \
  --password 'REPLACE_WITH_A_STRONG_PASSWORD' \
  --makerspace-name 'Space Works'
```

The command is idempotent. Confirm container health before provisioning domains.

### Fair-use limits and the storage counter

Managed fair-use caps (products/assets/machines/events/staff/storage/print/email/API-clients) activate
automatically once `PLATFORM_DOMAIN_SUFFIX` is set; they stay dormant on self-host. They are protective,
not a paywall — a superadmin can raise any cap per space via `resource_limit_overrides` in the Django
`/control/` admin (a numeric key, `-1`/`null` = unlimited; the `custom_domain` boolean grants a managed
space its own custom domain).

The per-space object-storage counter (`Makerspace.storage_bytes_used`) is maintained incrementally on
upload/delete, but the authoritative figure is computed by the management command. **When enabling managed
mode on a database that already holds evidence/print/image/document objects, run it once so pre-existing
usage is counted, and re-run it periodically to repair any drift:**

```bash
SPACEWORKS_COMPOSE_LAYER=saas scripts/spaceworks-compose.sh bundled \
  run --rm --no-deps backend --role management python manage.py recompute_storage
```

## 4. Provision a platform subdomain

As an authenticated active superadmin, call the provisioning endpoint for a makerspace:

```http
POST /api/v1/admin/makerspace/<id>/provision-subdomain
Content-Type: application/json

{"label":"kochi"}
```

This assigns `kochi.space-works.tech`; do not set a platform-suffix domain through the normal makerspace
settings update. The wildcard DNS record and Cloudflare Origin CA certificate already cover it.

## 5. Onboard a tenant custom domain

1. In the makerspace staff console, open **Settings -> Custom domain**, enter the complete hostname
   (for example `tools.example.org`), and save it.
2. Copy the displayed verification token. At the tenant DNS provider, create
   `_spaceworks-verify.tools.example.org TXT <token>`.
3. Create `tools.example.org CNAME origin.space-works.tech`. If that DNS provider offers proxying, keep the
   record DNS-only so the request reaches Space Works's Caddy with the tenant hostname intact.
4. Wait for both records to propagate, then select **Verify domain** in Settings. Verification
   requires the TXT token and the CNAME (or matching A address) before the domain becomes active.
5. Visit the domain. Caddy asks the fail-closed internal endpoint for authorization before issuing
   its first public certificate.

`DOMAIN_CHANGE_COOLDOWN_SECONDS` defaults to 86400 seconds in this overlay. After changing or
detaching a custom domain, the makerspace must wait for that interval before assigning another one;
changing the env value affects all makerspaces and should be an intentional abuse-control decision.

## 6. MinIO and browser-upload CORS

Inventory every browser-upload flow before changing CORS. Today the logical upload categories are:

| Category | Bucket setting | Access |
| --- | --- | --- |
| Issue/return evidence | `AWS_STORAGE_BUCKET_NAME` (`evidence`) | Private |
| 3D-print files | `AWS_STORAGE_BUCKET_NAME` | Private |
| Machine documents | `AWS_STORAGE_BUCKET_NAME` | Private |
| Warranty documents | `AWS_STORAGE_BUCKET_NAME` | Private |
| Public inventory/machine/branding images | `PUBLIC_IMAGE_BUCKET` (`public-images`) | Anonymous download |

Evidence, print, machine-document, and warranty-document objects share the private bucket by
default, but each remains a separate browser-upload flow that must be reviewed if storage layout or
headers change. `public-images` is the only download-anonymous bucket exposed through
`https://files.space-works.tech`; never grant anonymous reads to the private bucket.

Set `MINIO_CORS_ALLOWED_ORIGINS` (comma-separated) for the origins that perform direct browser uploads, including
the platform HTTPS origins and each verified custom domain. A presigned URL is a bearer credential:
any holder can perform the signed operation until it expires. Therefore do not enable credentialed
CORS, keep private buckets private, keep URL lifetimes short, and narrow allowed methods and headers
to those actually used. Upload flows need `PUT` or `POST`; signed/private reads may need `GET` and
`HEAD`; browser finalize requests go to the API, not MinIO. Avoid `DELETE`, broad headers, and a
wildcard origin unless an audited multi-domain policy requires them.

After changing CORS, re-run the `createbuckets` service (or apply the equivalent `mc cors set`
policy) and test one upload from every category above. CORS is enforced by browsers and does not
replace bucket policy or API authorization.

## 7. Operational notes

- Domain changes invalidate the backend's verified-host cache. If a domain appears stale, inspect
  the update/verification response and shared cache health before restarting services.
- DNS must resolve to `origin.space-works.tech` before verification and before Caddy can complete an ACME
  challenge. Propagation and negative caching can delay the first certificate; retry only after
  authoritative and public resolvers agree.
- Detaching a domain immediately removes it from the TLS ask allowlist, preventing new issuance or
  renewal. Caddy may retain an already issued certificate in `caddy_data` until it expires; DNS must
  be removed or repointed to stop traffic immediately. Do not delete `caddy_data` during routine
  deploys.
- This is a single-box architecture: Caddy, Django, workers, PostgreSQL, Redis, and MinIO share one
  failure and capacity boundary. Scale vertically and monitor disk/backup/CPU pressure first. Moving
  to multiple VPS nodes requires shared database, object storage, cache, and coordinated Caddy
  certificate storage or a different edge design.
