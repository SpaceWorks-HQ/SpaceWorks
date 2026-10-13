## Roles & access

Access is scoped **per makerspace and per action**. Super Admin is global; every other role is a
per-makerspace membership.

Authority comes from **actions, not role names**. A role is a row owned by one makerspace holding a
list of granted action strings (`view_inventory`, `accept_request`, `issue_direct_loan`,
`manage_machines`, …), and every permission check asks whether the actor holds the action — never
what their role is called. So a makerspace can rename, re-scope, or invent roles to match how it
actually works, and nothing downstream has to learn the new name.

Every makerspace starts with four protected default roles:

| Role | Granted actions | Notes |
|---|---|---|
| **Space Manager** | Everything grantable: full hardware lifecycle, inventory, QR, evidence, machines, events, bookings, audit, and makerspace settings | Must always keep `manage_makerspace` |
| **Inventory Manager** | Full hardware lifecycle + inventory + QR + evidence + audit | No machines, staff or settings |
| **Machine Manager** | `manage_machines` — every machine in the space, end to end: usage, warranty, maintenance, and handing finished jobs over | Implies `manage_printing` and `collect_service_request`, so it absorbed the old Print Manager |
| **Member** | None | A role granting no actions *is* a community membership — that is how staff and member invitations are told apart |

Beyond those, a Space Manager can **create custom roles** with any subset of actions they themselves
hold, and can edit the defaults — including renaming them and narrowing what they grant. One limit
protects the defaults from being edited into incoherence: Space Manager must retain
`manage_makerspace`. Protected defaults cannot be deleted; custom roles can be, once nobody is
assigned to them.

**Front-desk handover is a custom role, not a built-in.** Earlier versions shipped a protected
"Guest Admin", which handed every makerspace a role it might not want and made the one role people
most wanted to reshape the one they could not delete. Build the role your space actually has — call it
Front Desk, Duty Volunteer, whatever — and give it the handout actions: `view_inventory`,
`assign_box`, `issue_request`, `issue_direct_loan`, `return_request`, `upload_evidence`, and
`collect_service_request` to hand finished machine jobs to their owners. A role holding only these
gets a deliberately narrow console (Requests, Direct handout, Job handover) instead of the full staff
surface. Existing Guest Admin roles were converted in place and kept their name, actions and people.

Escalation is blocked in both directions: you cannot grant an action you do not hold, you cannot
create or assign a role carrying `manage_makerspace` (superadmin only), and you cannot modify a
membership that already holds it. `transfer_stock` and `manage_staff` are superadmin-only and are
never grantable to any role.

**Organizations reach across makerspaces.** A network, a university or a chain can be registered as an
organization, linked to any number of makerspaces as owner, manager or affiliate, and given staff whose
authority applies in every one of them — without a separate login or a membership row per space. An
organization grant confers **actions, never identity**: an organization administrator can hold
`manage_events` across the network's spaces while being Space Manager of none of them, and staff lists
still show only that space's own people, with a separate read-only view of which organizations reach in.
A makerspace that has hidden itself from the platform superadmin stays hidden — authority cannot be
routed in through an organization.

Outside this system entirely: **Public** users browse, submit requests, and — where enabled —
self-checkout and return eligible QR tools, gated on member presence and photo evidence.

> Earlier versions shipped five fixed, code-defined roles. Roles are now editable data; the four
> above are seeded defaults rather than the whole vocabulary.

Staff work in the **React console** at `/admin`; the superadmin-only **Django control plane** lives at
`/control/` (backend-only, never exposed on the public port). Two design rules are load-bearing — the
Request Workflow module is the single source of truth for state transitions, and the Inventory
Availability module owns all quantity math. Details in **[.github/CONTRIBUTING.md](../.github/CONTRIBUTING.md)**.

## Hosting

**The goal is to self-host inside the makerspace, on your own server** — your data, your network, no
third party. The [Quick start](../README.md#quick-start) is the recommended path. After it's up:

| Surface | URL |
|---|---|
| Public catalog | `http://localhost` |
| Staff console | `http://localhost/admin` |
| API | `http://localhost/api` (Swagger at `/docs/`) |
| Django control plane | `/control/` on the backend only — **not** exposed on the public port |

Create the first superadmin + makerspace (the wizard does this for you; for a manual instance):

```bash
scripts/spaceworks-compose.sh bundled run --rm --no-deps backend --role management python manage.py setup_instance
```

With no arguments it creates **`superadmin` with a generated password**, prints it once for you to save, and forces a password change on first login. Re-running setup keeps the existing password and does not print it. Supply `--password` or `SETUP_SUPERADMIN_PASSWORD` to choose your own credential.
Guided installs pin the latest published GitHub release built from `main`. Manual updates, the Platform
panel and the seven-day cron select the newest published, non-draft, non-prerelease main release
(`X.Y.Z-main.<run>.<12-hex sha>`), with a backup and readiness check. If deployment fails, the
application containers return to the previous retained release. Run
`bash scripts/update.sh --force` on Linux or Windows Git Bash for an immediate
update; see **[docs/self-hosting.md](self-hosting.md)** for scheduling, pinning, TLS, and recovery.

**No server of your own?** Space Works is multi-tenant — partner with a nearby makerspace to run your space
as a tenant on their instance. **Prefer managed Postgres?** The database URL must live in the versioned
pointer/CAS adapter, never ambient shell state. The Cloud static-environment initializer and D7 provider
callbacks are not implemented yet, so the older Supabase path is suitable only for a non-H1 demo—not a
supported restore topology.

### Split deployment: backend on your server, frontend on Netlify

Supported, and `netlify.toml` in the repo root configures it. Netlify builds **only** the React app —
it never touches the Dockerfiles or compose files, and because `frontend/src/generated/api.ts` is
committed, the build never has to reach your server.

Netlify picks up `base = frontend`, `npm run build`, `publish = dist` and `NODE_VERSION = 22` from
that file (Vite 8 needs Node 20.19+/22.12+, and Netlify's default image can be older). It also adds
the catch-all rewrite to `index.html`, without which every deep link — `/m/<slug>`, `/admin/*`,
`/event-check-in/<token>` — 404s on refresh. Set **`VITE_API_URL`** in the Netlify UI to your API,
e.g. `https://api.example.org/api`.

The backend then has to accept a browser on a different origin. Auth already defaults to cross-site
cookies (`AUTH_COOKIE_SAMESITE=None`, `AUTH_COOKIE_SECURE=True`), **which only works if both sides
are HTTPS**:

```env
ENABLE_HTTPS=True
ALLOWED_HOSTS=api.example.org
CORS_ALLOWED_ORIGINS=https://your-site.netlify.app
CSRF_TRUSTED_ORIGINS=https://your-site.netlify.app
```

Three more that are easy to miss:

- **Set each makerspace's `frontend_domain`** to the site's domain. Origin scoping validates it, so
  tenant-scoped routes are rejected without it.
- **Object storage must be addressed publicly.** `AWS_S3_PUBLIC_ENDPOINT_URL` and
  `PUBLIC_IMAGE_BASE_URL` are baked into presigned URLs and every public image `src`, so a
  `localhost` value yields a site that works only from the server console and shows broken images to
  everyone else. On R2 or S3 also set `STORAGE_PRESIGN_METHOD=put`, and allow your site's origin in
  the bucket's CORS rules **in the provider dashboard**.
- **Keep a scheduler.** Hosting the frontend elsewhere does not affect scheduled work, but the
  backend profile you choose does: `docker-compose.prod.yml` runs Celery `beat`, while
  `docker-compose.cloud.yml` has no beat and relies on its `cron` service instead. With neither,
  `.delay()` still runs inline so nothing looks broken, yet return reminders, the evidence-retention
  sweep and event-series extension silently never fire. If you use the cloud profile, drop only its
  `frontend` service — never `cron`.

### Moving a makerspace onto its own server

A space that started as a tenant on someone else's instance can take its data with it. A superadmin
on the source deployment exports that one makerspace — rows, encrypted personal data, and the
space's uploaded files, all inside a single `age`-encrypted archive — and a superadmin on the
destination imports it as a new tenant.

Three things are deliberate, because this moves real accountability records:

- **Whose personal details travel is approved explicitly.** The export lists the exact people whose
  contact details the archive would contain and requires a source superadmin to approve that list.
  Anyone not approved is carried as an opaque reference instead. Approval is bound to that exact
  list, so if it changes the approval no longer counts.
- **Only one deployment is writable at a time.** The source freezes its writes before the final
  snapshot and stays frozen through cutover, so nothing committed after the export can be lost. The
  destination stays closed to users until every file has been copied and verified.
- **The source is archived, not deleted** — and archives are outside the purge guarantee.

Both sides are driven from the staff console; nothing here needs a shell.
