# SpaceWorks — condensed project history

> **This is the history half of `CLAUDE.md` / `AGENTS.md`.** It was split out when that file crossed the
> harness's memory-file size limit; nothing was dropped in the move. It has no `AGENTS.md`-style twin —
> both names of that document point at this one path, so edit it in place.

## Condensed changelog (newest first — full detail in `git log`)

- **2026-09-03 — 0.8.1: split-frontend deployment, and a verification round that finally ran.**
  `netlify.toml` makes backend-on-your-server plus frontend-on-Netlify a configured topology rather
  than a guess: Netlify builds only the React app (the generated API client is committed, so the
  build never reaches the server), Node is pinned for Vite 8, and a catch-all rewrite stops every
  deep link 404ing on refresh. README documents the cross-site cookie, CORS/CSRF, `frontend_domain`
  and public-object-URL settings the split needs, plus the scheduler caveat that the cloud profile
  relies on its `cron` service where prod runs Celery beat. The same batch executed phase 10's
  backup/tenant-migration round-trips for the first time (1517 passed, 0 failed), which closed the
  check-in `operation_id` collision question without a schema change; added a catalog-driven guard
  asserting every projected model's primary key is importable and every deployment-global unique
  column has a collision rule; and removed a duplicated `LandingPage` that left the extracted
  module dead code.
- **2026-09-02 — Events-programme round-trip hardening after integration.** The phase-10 graph exposed
  defects that declaration-only guards could not: `EventSeriesCollaborator.series` and `.makerspace` were
  unclassified cross-tenant edges, so tenant projection refused them until the rules explicitly matched
  occurrence collaboration and dropped a half-owned grant; the encryption plaintext-leak sweep had no
  builders for the new PII in `EventFeedbackResponse.answers_snapshot` or
  `EventAttendanceCertificate.recipient_name`, so both immutable models gained real sentinel builders.
  Evidence retention then proved a more general migration trap: a `OneToOneField(primary_key=True)` leaves
  no `id` column and is outside the importer’s supported auto-integer/UUID primary-key shapes. Both retention
  models now have normal `BigAutoField` primary keys plus unique one-to-ones, and materialization reads the
  model’s actual PK attname through `source_pk()` rather than assuming `row["id"]`; the multi-tenant fixture
  also stopped reusing a globally unique calendar-feed digest. The final round-trip fixes made an empty
  sovereign-row projection produce a correctly typed empty marker instead of raising Django’s
  `EmptyResultSet`, skipped nullable object keys instead of capturing an object literally named `"None"`,
  withdrew the organization-events URL when the separable events app is tombstoned, limited organization
  analytics choices to reports with a server aggregation strategy, and made the migration harness release
  source-only immutable operation UUIDs/certificate serials before modelling a clean target
  (`abccb738`, `622aac8c`, `a674197f`).
- **2026-09-02 — Twelve-phase events, modules, organizations, reporting and evidence programme.** **Phase
  0** repaired six module-cascade defects: core staff request issue/return now gate by their own URL surface
  instead of the optional `guest_handover` module, events/bookings declare their membership dependency, and
  `backend/tests/modules/` now exercises module-OFF behaviour through the complete box→issue→return loan
  spine. **Phase 0a** corrected five report gates/builders so disabled printing, machine-service, membership
  and asset-unit data cannot leak through the wrong module key. **Phase 1** split the events schema into
  focused `models_*` modules behind the stable `models.py` re-export barrel. **Phase 2** added an exclusive
  absolute-or-lead-time registration cutoff, optional approval/rejection, approval-aware uniqueness and
  FIFO waitlist promotion; paid applicants are charged only when they become registered. **Phase 3** added
  immutable, source-aware check-in history, immutable feedback answer snapshots, and PDF attendance
  certificates that require `attended` status and revoke on attendance correction. **Phase 4** materialised
  recurring `Event` rows from an `EventSeries` so registrations, payments and audit targets stay concrete;
  recurrence anchors to local wall-clock date/time plus an IANA zone across DST and can be extended by both
  staff and the no-beat cloud scheduler. **Phase 5** shipped public/member ICS, rotatable digest-only bearer
  feeds, RRULE/VTIMEZONE series export and printable badges whose QR reuses the registration check-in token.
  **Phase 6** added minimal expiring offline rosters and idempotent late sync, plus an event/window-scoped,
  rotated, hashed-and-peppered PIN station with uniform public failures. Its merge kept
  `DeploymentRecoveryGateMiddleware` at `MIDDLEWARE[0]`, ahead of calendar-token log redaction; classified
  `EVENT_STATION_PIN_PEPPER` under the **EXACT fingerprint** restore policy; and put the anonymous station
  write points through `assert_write_allowed` so they cannot create tenant state after a tenant-migration
  source gate closes. **Phase 7** kept makerspace as the tenancy anchor while adding organization public
  profiles/catalogues, separate governance actions, single-use invitations and managed event organizers.
  **Phase 8** added module-complete composite reports, charts, and append-only cursor/fence rollups, with an
  explicit aggregation strategy or exclusion reason for every report key. **Phase 9** implemented evidence
  retention mechanism A: delete final and staging object bytes after the effective window, retain immutable
  `EvidencePhoto` metadata, record a truthful terminal expired state, return 410 on reads, and preserve the
  tombstone through backup/migration. **Phase 10** built the real recurring-series→occurrence→registration→
  attendance→feedback→certificate object graph and proved field-by-field deployment-backup and tenant-
  migration round trips across module-on/off, retained-disabled and archived tenants, expired evidence and
  report rollups; it also made the retention sweep bounded, dry-runnable and observable through a structured
  completion summary (`007e508a`, `2bb7a3d3`, `ef44d212`, `212eaeba`, `141f852f`, `cc02ad4b`).
- **2026-09-01 — SpaceWorks 0.8.0 release (PRs #15 and #16).** PR #15 first published the cumulative 0.7.5
  tree, then PR #16 advanced `VERSION` to `0.8.0`; `origin/main` landed at `b15c4e11`. The release completed
  the post-Part-A backup/migration work: compound deployment archives gained tenant-recipient-only opaque
  slices, a verified sovereign-row-free readable main, typed n-way object ownership, bounded DEK rewrap,
  signed outer manifests, durable component/custody ledgers, create-only staged promotion, serialized
  activation, pre-mutation import validation and an H1-supervised restore/cutover/rollback path. Tenant exit
  gained a deny-by-default field/authority projection, constrained scratch-database materialization, frozen
  capture and recipient revalidation, readable outer envelopes, target identity/readiness checks and broad
  acceptance coverage; critically, the source gate moved its shared advisory lock to a dedicated connection
  and verifies backend continuity so it remains effective behind a transaction pooler. Operations gained
  coverage-proved scheduled backup runs and restore preflight, while the producer capability marker binds
  installed privileged-script and entrypoint hashes. The same release added the curl-first pinned-image
  installer, upgrade-time per-makerspace module selection and the native-Windows/WSL2 support boundary;
  renamed the opt-in `accounts` module to `member_accounts`; added machine-type-scoped/public coloured
  filament pools; and split over-ceiling modules behind compatibility barrels. The 0.8 increment then made
  core public borrow proposals work when membership is off and added opt-in account-less requests using one
  inert, credential-disabled makerspace principal, unverified contact snapshots, `actor=None` audits, required
  idempotency and IP/email/outstanding limits. Telegram became outbound-only, the staff sidebar became a
  tested dock, and release hardening preserved OCI child manifests, recorded executable bits in Git so
  tarballs can restore, and fixed the compose-wrapper validator import (`5bf555b0`, `728fcbf6`, `32f4f306`,
  `b15c4e11`).
- **2026-08-22 — Archive-recipient custody, Part A (K1 landed + the two-recipient floor).** A tenant archive
  is encrypted to the makerspace's own verified `age` recipients, and the platform is added **only** when
  `superadmin_access_enabled` is true — so with the switch off the operator can *run* a tenant backup but
  cannot *open* it. Scope is deliberately narrow: **deployment backups still contain every makerspace's rows**
  (Lane E unbuilt), so this is not yet "excluded from my platform backup". Fixed a latent K1 bug where
  `superadmin_access_at_decision` was written by nothing, so a switch flipped between an archive's request
  (web) and its build (Celery) silently changed who could decrypt it; selection now fails closed on a missing
  snapshot instead of reading the live flag. Added `MakerspaceArchiveCustodyState` as the authoritative alarm
  record, a **two-recipient admission floor** (ordinary revocation refuses below two; **compromise always
  proceeds**; one recipient keeps backing up degraded; zero fails closed on build), and a single
  makerspace-first lock through which every count-changing transition now passes — correcting
  `verify_recipient`, which locked the recipient row first, and `reactivate_recipient`, which locked nothing.
  Creating a makerspace with the switch already off is refused. Recovery is never blocked by a tenant's
  custody posture: **fail closed on build, not on restore.** Two migration bugs were caught before shipping —
  a constraint violation, and `AddConstraint` after `RunPython` in one migration, which aborts on any real
  upgrade but passes on a fresh database. Rules in `docs/INVARIANTS.md`; supersedes Lane K1's "recipient
  mutation takes no lock" and its one-recipient switch-off. Still open: no outbound alarm channel (readiness +
  admin only), and the two-release rollout is operator discipline, not enforced by code.

One line per shipped batch. The rules these introduced live in `docs/INVARIANTS.md`; use
`git log --oneline`/`git blame` for the implementing commits and per-file history.

- **Audit attestation, API-client scopes, organizations** (2026-08-19, `dev`, local): three tracks off
  the plans in `docs/superpowers/specs/2026-08-19-audit-api-org/`. **AUD-1/AUD-2** — a keyed per-row MAC
  over every audit row with a bound, signed cutover, then signed Merkle batches over sets of rows
  (`AuditBatchLeaf`, anti-join for unbatched rows) because the `pg_snapshot_xmin` watermark was
  provably wrong: xids and sequence values are independent. **ORG-1/2/2b/3** — `Organization` as a
  platform entity spanning makerspaces, `OrganizationMembership` conferring ACTIONS (never identity)
  through an rbac branch, then the staff-login gate, auth payload and action-gated prefilters that make
  that authority reachable, and `EventOrganizer` attribution. **APIB-1/2/3** — native app registration
  and revocation across every device-token path, then a frozen registry of all 31 protected routes keyed
  on the versioned `view_name`, made authoritative behind a frozen `legacy:v1` cutover grant.
  Alongside them: **F4** made every presigned upload land in staging so an accepted evidence photo can
  no longer be replaced through a still-valid presign, and a **proven** HMAC replay was closed — the
  optional nonce slot let a captured signature be replayed with the nonce moved into the request body.
  The full-suite gate then caught 42 failures from three root causes (an undeclared audit-meta id path,
  a self-checkout gate ordering, and an audit key cache consulted before the configured check), all
  fixed. Rules in `docs/INVARIANTS.md` under **Organization accounts** and **API client scopes**.
- **Phase 5B — per-makerspace tenant migration, managed → self-host** (2026-08-17/18, `dev`, local):
  `apps/tenant_migration/`. `ExternalTenantReference` + export transform, PORTABLE raw-column PII reads,
  reference dispositions, DEK carry with the archive streamed into `age`, import job + per-person identity
  decisions, one-shot insertion, target-owned projection, the `IMPORTING`/`ACTIVE`/`ABORTED` lifecycle,
  signed single-use cutover receipts, row-level closure for movable assets/QRs/inbound transfers, the
  lock-protocol source gate, objects carried inside the archive with a promotion journal and pre-activation
  verification, and the closure-admission rule + superadmin API/console. Suite **3879 passed**.
- **Account recovery, account-less members, data export, deployment backup** (2026-08-16, `dev`, local):
  **Phase 8** emailed-OTP recovery (`PasswordResetEnvelope`, at-most-once drain with generation fencing),
  which also closed two **pre-existing** TOCTOU races in the legacy reset link and `change-password`;
  **Phase 7** account-less member surfaces (`is_walk_in` trigger, claim route matrix, claim codes, bounded
  claim session, imported-membership adoption, OIDC browser flow); **Phase 4** Space-Manager data export
  (`apps/data_export`); **Phase 5A** deployment backup + restore (`apps/backup`). Suite **3647 passed**.
  Three defects surfaced only at integration, which is the argument for merging early: Phase 4's export
  purge was registered in `CELERY_BEAT_SCHEDULE` but **not** `SCHEDULED_TASKS`, so a beat-less cloud
  deployment would have retained expired archives and their download tokens forever; phases 7 and 8 added
  models with no export disposition and the registry guard refused them; and a `.venv` **symlink got
  committed** from a build worktree — checking it out later destroyed the real virtualenv, because
  `.gitignore` never untracks an already-tracked path.
- **Public imagery, machine grouping, accessibility** (2026-08-10, `dev`): `Event.image_key` with
  presign/attach/clear, and `image_url` on the staff and public serializers; machines grouped under their `MachineType` in the console plus a display-only public
  `/machines` page; accessibility floor (contrast guard, focus indicators, skip links, 44px targets,
  labelled landmarks). **The pastel theme was kept** — only `--color-muted` failed AA. Blueprint grid and
  Instrument Sans confirmed intentional and waived in `.impeccable/config.json`.
- **Notifications v2** (2026-08-09, `dev`): per-event recipient selection (`9d8d5a7`); per-room chat
  destinations with typed credentials and a per-channel length table (`f7fd8b2`); editable email wording for
  four FabLab streams + one shared chat body per event (`69b8e45`); recipient rules narrowed by
  machine/type/category (`6eca688`); staff API + console with write-only credentials (`99dcb00`).
  **Per-destination Telegram bot tokens considered and dropped** — one webhook secret means a second bot's
  accept/reject buttons would be dead.
- **Auth + notification-channel modularity** (2026-08-08, `dev`): SMS provider seam + phone as a verified
  member login identity (`f04fbb5`); guided-but-skippable Google sign-in in the installers +
  `configure_social_auth` (`1210208`); Discord channel and one module key per notification channel, with the
  `0056` slack/mattermost backfill. **SAML and per-makerspace auth credentials considered and dropped** —
  OIDC covers every IdP a makerspace runs, and identity is platform-scoped by construction.
- **Phase C final tracks** (2026-07-23, `dev`): encrypted per-space Stripe credentials + managed Stripe
  Connect (`3b43f47`); scoped reconciliation dashboard/reports (`1ad63f5`); unified booking,
  event-registration and membership-dues Payment subjects (`159a88f`, hardened by `396cb27`); attested
  device grants, rotating native refresh, native push, Stripe PaymentSheet (`1aa2029`); server-verified
  Google/Apple member + staff social sign-in with surface/origin enforcement (`ad2fe42`).
- **Phase C — capabilities + payments + geofence** (2026-07-21/22, `dev`): two-level module/feature toggles
  (`41e6a2a`); C.2 Stripe foundation, verify-only webhook (`92eda37`); C.3 machine-service payments —
  `Payment` as single authority, non-blocking charge at `complete()`, idempotent settlement, legacy
  `payment_*` → read-only historic with backfill (`9c1d928`); C.7 **advisory** geofenced check-in
  (`007ef55`); C.3-hardening — DELETE-immutability trigger, purge-graph wiring, async checkout settlement
  (`c8225c0`); C.6 + P1-A custom machine-type config, generic `MachineServiceConsole`, and per-space
  `MakerspaceMachineTypePricing` (pricing out of `capability_config`; `0018` fail-safe backfill) (`8d39cb0`).
- **FabLab Parts C–N + L + H + Settings + K** (2026-07-16→18, `dev`): Events, Bookings (+ public
  self-booking, shared `forms_schema` custom forms, structured event location), Maintenance, Analytics
  reports, public Roadmap (later tombstoned), Machine Manager role + SM-delegated role assignment,
  per-feature×per-channel notification matrix, scoped PII encryption H1–H4, custom roles L, machine service
  requests N. New apps: `events`, `bookings`, `maintenance`, `roadmap`, `forms_schema`, `encryption`.
- **Machines module M1 + M1.5** (2026-07-14/15): generic `apps/machines/`, 3-tier authz (`MANAGE_MACHINES`
  + type-managers via `MachineType.managing_action` + per-machine operators), services as single source of
  truth, printer auto-link, custom types, photo, warranty (3rd host), consumables (count via inventory +
  grams ledger), public exposure.
- **Self-host-first + SaaS hosting Parts A/B + space-works.tech** (2026-07-15/16): self-host custom-domain
  auto-trust, managed fair-use limits + subdomain request→approve, one-shared-instance multi-tenant hosting
  (all dormant on blank `PLATFORM_DOMAIN_SUFFIX`). AGPL relicense + repo professionalization.
- **Audit fixes + dependency upgrade P1–P17** (2026-07-08): integration health center, scan-first stocktake,
  ops dashboard, notifications app + inbox + fail-safe emit hooks; force-latest upgrade to Django 6 /
  React 19 / Vite 8 / Tailwind 4 / TS 6.
- **Manager fixes P5–P10** (2026-06-30): direct-loan return resolutions + accountability + public
  report-a-problem, unified asset editor, optional partial approval, accountability dashboard, actionable
  warranty/reports UI.
- **Email/async stack** (2026-06-21): `EmailLog` outbox + single `dispatch_email` choke point + Celery/Redis
  async delivery + retry. Per-makerspace staff-notification recipient matrix.
- **Print filament grams / payment / manual logs** (2026-06-16/28): requester grams estimate, failed-% →
  printer hours, manual-log outcomes, staff-private cash payment on prints (never exposed to the requester —
  enforced by serializer split), top-requesters leaderboard by email.
- **Warranty tracking** (2026-06-27): `apps/warranty/` (asset XOR printer XOR machine host, private
  bill/doc uploads, display-only status; per-host RBAC; public-leak invariant tested).
- **UI reskins** (frontend-only): pastel "notebook" theme (2026-06-22, fill/`-ink` token split), Blueprint
  redesign + item/makerspace imagery (2026-06-20).
- **Collaborative self-governance** (2026-06-16): superadmin-access toggle (later hard block), API-client
  self-serve, admin + self-service password resets, Platform Email settings.
- **Console-parity + workflow surfacing** (2026-06-16): broken-at-handover + to-be-fixed shelf, ledger
  specific-unit + staff-return evidence, direct-handout UX, lending history, QR rebind, surfacing ~10
  orphaned backend lifecycles into the React console.
- **Deploy / production** (2026-06-19): single-tenant branded frontend, Supabase free-tier dual-mode
  (env-toggled; localhost default unchanged), lean-paid production deploy artifacts + perf hardening.
