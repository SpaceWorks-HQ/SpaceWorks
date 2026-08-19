# SpaceWorks — condensed project history

> **This is the history half of `CLAUDE.md` / `AGENTS.md`.** It was split out when that file crossed the
> harness's memory-file size limit; nothing was dropped in the move. It has no `AGENTS.md`-style twin —
> both names of that document point at this one path, so edit it in place.

## Condensed changelog (newest first — full detail in `git log`)

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
