# Changelog

Releases are published from `main` and titled **`SpaceWorks <version>`**. The root `VERSION`
file selects the series; each build is tagged `v<series>-main.<run>.<sha>`, which is what a
deployment pins to. Bumping `VERSION` also requires bumping
`SPECTACULAR_SETTINGS["VERSION"]` (`backend/tests/test_version_consistency.py` enforces it) and
regenerating `frontend/openapi-schema.json` and `frontend/src/generated/api.ts`.

Entries up to 0.2.0 below were generated automatically from conventional commits. That
generation stopped afterwards, so **0.3.0 through 0.5.1 were never recorded here** — for that
window see `git log` and the condensed changelog in `CLAUDE.md`, which also carries the design
rule each change introduced.

## 0.7.5 (2026-08-11)

### Features

* **events:** cross-makerspace collaborative events — a host invites another makerspace, which
  accepts or declines, and the partner's members then discover and register through their own
  member area. Registration records durable provenance, so later edits to the collaborator list
  cannot erase a member's history or void a QR already issued
  ([799804d](https://github.com/SpaceWorks-HQ/SpaceWorks/commit/799804d101a1ef74a17a20ef0a4332715bd675ba))
* **events:** a visiting member accepts the host's waiver on the registration itself, rather than
  by manufacturing a membership at the host — which would corrupt the host's roster, quotas, dues
  and member reporting. Audited by waiver id and version, never by body
  ([dab0354](https://github.com/SpaceWorks-HQ/SpaceWorks/commit/dab035456decbfb3315533354a345fa255761311))
* **events:** QR check-in for event registrations. Resolution is read-only and answers unknown,
  malformed and wrong-event tokens identically, so it cannot be used to tell them apart
  ([d59f38d](https://github.com/SpaceWorks-HQ/SpaceWorks/commit/d59f38d6ded06592f8041517d24cc5c3af39d8bd))
* **members:** opt-in publication of recently attended events on a maker profile, consent-gated
  separately from the rest of the profile because attendance is not something the member typed
  ([9ed0fcb](https://github.com/SpaceWorks-HQ/SpaceWorks/commit/9ed0fcb5af38994f67180cd0746e26b34abe7873))
* **events:** registering no longer requires an active presence session — signing up is planning
  to attend, not attending. Presence is proven at the door by the staff-scanned QR, and the nine
  other presence-guarded surfaces are unchanged
  ([f16896f](https://github.com/SpaceWorks-HQ/SpaceWorks/commit/f16896f5062010f44e6b3eca1aeb6252a93ef632))

### Bug Fixes

* **payments:** a purged `events` module no longer strands collaborative-event money. Routing
  moved off the registration's provenance — which a purge deliberately clears — onto a new
  `Payment.via_makerspace` column no purge touches. Previously a collaborator purging `events`
  made a host-raised charge invisible in the member's own area while the host still refused them,
  so a receipt vanished and a pending charge became impossible to settle
* **events:** closed a rate-limit bypass on collaborative registration without blocking waiver
  repair. New registrations share one `event_register` budget per member across both the public
  and collaborative routes; retries are bounded on their own scope, so an exhausted create budget
  can never stop a member repairing a registration that holds no waiver acceptance
* **events:** the check-in scanner no longer tells correctly-accepted members to get a waiver.
  Evidence lives in two places — a visitor's on the registration, a host member's on their
  membership — and the endpoint read only the first, making it structurally false for every host
  member. It now reports `not_required` / `on_file` / `missing`
* **events:** the scanner no longer offers a Confirm button that can only fail. The resolve
  response carries `event_status` and `confirmable`, mirroring the precondition that marking
  attendance actually enforces

### Changed

* **release:** GitHub Releases are now titled `SpaceWorks <version>` instead of `v<version>`
* **api:** the OpenAPI document version tracks the release series. It had sat at `0.1.0` while
  `VERSION` climbed to `0.5.1`, so every schema consumer was told a version that had never been
  true of anything

## [0.2.0](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/compare/v0.1.0...v0.2.0) (2026-07-14)


### Features

* 3D printing manager with role-based request lifecycle and email alerts ([cd102c5](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/cd102c50468a507cf2ef7b242d5edcce2ebdcc24))
* add hardware return flow ([951ffa6](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/951ffa6c8d4d055cb759bd3859ef568baea87351))
* **admin:** comprehensive Unfold sidebar (inventory/requests+loans/operations/3D printing/accounts/integrations/audit) covering all registered models ([9f9d3aa](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/9f9d3aa8bc02940c56555ed16683af177c5a214f))
* **admin:** register PublicToolLoan/ReturnEvent/RequesterAccountability/HardwareRequestItemAsset/BoxScan (read-only) + MakerspaceMembership + per-makerspace list_filter; doc Phase 3 in CLAUDE.md ([6057e8a](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/6057e8a706e4e353af31869f2ad7b908cfd2a7bb))
* **admin:** superadmin-only Unfold control plane + workflow admin actions + U-SEC hardening ([afd28e4](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/afd28e411b81e9fbec92539b2209cbe33b98e801))
* **attribution:** show accepted-by/issued-by in lending history + requests queue; deterministic lending order + stable keys ([8f8d7e0](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/8f8d7e011b92c16497fcff737330da6fef97503d))
* **backend:** ledger + extended/aggregate reports + 3D printing reports + first-run superadmin/forced-pw-change + audit pagination ([4f629d1](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/4f629d1b1ecda09e9d17746de57f0a0fce4c4e03))
* **brand:** rebrand to OSMM — Open Source Makerspace Manager (logo in headers, README, display names, docker) ([3cbc306](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/3cbc306a390fec6f4056e82f1b0c7691963a3315))
* **categories:** staff-console category CRUD (API+tab+product selector), EDIT_INVENTORY-gated ([d6ec21c](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/d6ec21c0a6129a287ed6901f456fdf216a72426b))
* collaborative-makerspace self-governance (superadmin-access toggle, API-client self-serve, password resets, platform email) ([7281a27](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/7281a27229dcae150df5f3266da11111c5abbee4))
* **containers:** staff Containers panel (edit/move/contents/history) + per-asset QR reprint ([8f4bb61](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/8f4bb61815c970e77fbb955eb06b8ae5e82b27d2))
* **control:** superadmin Django admin monitoring surfaces for QR/evidence/print artifacts ([fa4a994](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/fa4a99492b0c9baa9224205389fcf9d1c914b12d))
* **direct-handout:** all in-stock products, container picker, blocking check-in verify ([9cc6336](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/9cc6336066c67433a73270a3f235fb0f7a1eabba))
* **email:** Celery+Redis async delivery + retry endpoint/button (off-request SMTP) [phase 3] ([e660109](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/e660109bbacc4943de05056466edc764e2b4cb38))
* **email:** EmailLog model + single dispatch choke point + staff email-log panel [phase 2] ([fa834b1](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/fa834b11ce6c19c93c18e1598657d3d24bc70a4d))
* **email:** mute-matrix phase 1 — per-makerspace event mutes by role/requester (model, rules, wiring, tests) ([e0a0700](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/e0a0700fb6329b172232bb9faf014de19c570afe))
* **email:** mute-matrix phase 2 — notification-rules GET/PATCH API + read-only admin + tests ([dc42b1f](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/dc42b1f544888dacff29a8007032a6c8b4f51df1))
* **email:** mute-matrix phase 3 — React mute matrix UI in makerspace settings + OpenAPI/TS sync ([6483a63](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/6483a6342b38f473e6c85fd5c17563cb7f885b61))
* **email:** role-gated email-template API (list/get/patch/reset/preview) + regen OpenAPI [phase 4/6] ([d451a08](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/d451a08ec61e85bd76d445dbdf28c20a8800fd9e))
* **email:** staff-console Email Templates panel (palette + sandboxed live preview + reset) [phase 6b] ([4e6c198](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/4e6c198f9e725c3128de91bc7e0765129e59eec6))
* **email:** unified EmailTemplate model + 27-template registry + data-migrate old rows [phase 2/6] ([2cbc4b3](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/2cbc4b39f81ca30b2e6ea6ab07e5c74a51c86e28))
* **email:** unified render engine + rewire all 4 send paths + drop HardwareEmailTemplate [phase 3/6] ([e1609a6](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/e1609a66dc0b85a536755b94471ac66a3a7c13b4))
* enrich submitted-request Telegram alert with contact + items (length-capped) ([7f6dff7](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/7f6dff7373a6aff02bf67c35bdfb290bfdd14e64))
* **evidence:** expose issue/return evidence ids + view issue/return photos in staff console ([5dfad0f](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/5dfad0f03f68e5ac3e92ee410aee3e8181690c93))
* **evidence:** in-console photo upload for issue/return (presigned), replacing manual evidence id ([e707576](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/e707576cffd5bb09b3a921447f81b4ad27da60bd))
* **frontends:** staff Tenant-frontend registry panel (list/create/edit, MANAGE_MAKERSPACE) ([75a82cb](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/75a82cb7c42f2f46540fa461b5380d3284c127de))
* **handout:** multi-item direct handout + in-browser camera QR scanner ([8541f45](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/8541f45746cd4787dbc528578151c5a5f1ef199c))
* hardware issue/handover (box scan + issue photo, reserved→issued) ([241dde6](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/241dde6bd0074a5a93b67c9f094856373d7a785e))
* hardware request workflow (public submit + admin accept/reject) ([6f52c07](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/6f52c07598c52332f199b429f99c6aba92e26f68))
* **hardware:** asset-QR scan at reviewed-request issue + history view + contact/damage display ([10dd0e0](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/10dd0e068615558423ca9841f2b1284b824a222c))
* **hardware:** terminal request-history endpoint + item tracking_mode/requires_asset_qr ([d4ec8dc](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/d4ec8dcef762a4f46f625471e1d3808b2ed43832))
* **identity:** require name+email+phone across borrow/handout/print/self-checkout, key check-in on email, show borrower names in public stats ([0863b6b](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/0863b6b563b57e0cc33d593c285c1cc7786a272a))
* **inventory:** add-to-To-Buy action + out-of-stock prompt [asset-move phase 3: frontend] ([4b842bd](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/4b842bd5c578a2cc792235376c44412a0edf8fad))
* **inventory:** per-item lending history for audit-capable staff (soft-hide aware) ([499d7d4](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/499d7d444ab1d6b548deca28e31a30c6a5078d01))
* **inventory:** per-makerspace categories + public category browsing; admin 'Inventory' relabel ([154e549](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/154e5497e0291c99b3a35ada7bc2ca0898a75e30))
* ledger container column + return-modal overflow fix + spool colour swatches [phase 1] ([8a5795a](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/8a5795aef377e5f4492b91649fc5f31747820f10))
* **loans:** empty-container direct handout + ledger visibility [phase 1: backend] ([c3b9fc5](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/c3b9fc5ccdcd85dd4b06a3a23896cf7e4d4758e7))
* **loans:** scan-container button for empty-container handout [phase 2: frontend] ([5cdb0bf](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/5cdb0bf490c384abbcad8453f1ff0b8a2fdce27e))
* **makerspaces:** GPS map link in staff settings + public directory/item Open-in-Maps [phase 6a] ([904fcb4](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/904fcb44832e7f1ddab23bff6e751f9e03aca178))
* **makerspaces:** per-makerspace Google Maps link (validated map_url) [phase 1/6] ([a3742f5](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/a3742f57416200138f30f12f62db632882d9597b))
* **makerspace:** superadmin archive→purge lifecycle + hard-hide hard block & printing-report 403 ([41b078d](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/41b078d65f7628f32af57e4a37b3464e3ff62ac7))
* operations + multifrontend platform baseline + operations OpenAPI docs ([d03beb2](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/d03beb227fc59d48e3304a2a08aff93e3e474c91))
* per-client rate-limit tiers for HMAC-verified server clients ([571c613](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/571c613d6dfb6a6569c2f2ec3199ba7ef381069c))
* printer hard-delete, unified Requests tab, public upload fix, email-only status ([42832dd](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/42832ddc5129da7d7a3456664dc550c4c187b360))
* printer images + Django /control/ parity + About page + password-reset email config ([a71a196](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/a71a196758fcc5368fceb9c1b97a14039ed28732))
* **printing-reports:** add top requesters (most print jobs by requester) + frontend table/bar chart ([96e9cc0](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/96e9cc0bcc4b431dfb9197a72c92305689795909))
* **printing:** brand field in spool create form + show brand & grams-used per spool (weight defaults to 1kg) ([05f6ad2](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/05f6ad2dbe318706b6f172a4d5c5fcbc450698fe))
* **printing:** delete filament spools (409 when referenced by print requests) ([2320b50](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/2320b505aa7f39d48450fc919f76fc7da7976cc4))
* **printing:** fail/reprint lifecycle — partial waste, reprint cloning, per-printer outcomes report ([33a0508](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/33a0508f614d4bad2e39637afc5ce3f598dbcd08))
* **printing:** live print countdown + status-card UI fixes (overflow, dark autofill) ([0cb71c1](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/0cb71c14065ece9f53494d96045c7dfe8d28d4a6))
* **printing:** manual print log (spool deduction + printer reports) ([59cc5f6](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/59cc5f69217779b9c9abd733cb36eb9c54dc4307))
* **printing:** print public_token + contact fields + staged PrintRequestFile model & storage ([836fa27](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/836fa27fed94636595f44cf14e24bda98dd285a2))
* **printing:** public 3D-print request API (Check-In, honeypot, presign, atomic submit, token status) ([5f13454](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/5f13454ba328d994631eafe3bec9435b69e912a5))
* **printing:** public 3D-print request page + status stepper + buckets endpoint ([ee8ea11](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/ee8ea11ef38974c755f9565b275ecb0228d2e274))
* **printing:** show queue position in public print status tracker ([4ffe976](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/4ffe976ffc6d5967a1314603932d293a2158b281))
* **printing:** staff pending accept/reject queue + read-only history + printer-status start filter ([a398a70](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/a398a70fe1390a27da903a50cd330035d3348d25))
* **printing:** staff sees brief/contact + downloads request files via signed view URLs ([c54d5f1](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/c54d5f1f9768e441053029169856bb17d0bce3fc))
* **printing:** staff-private cash payment + collected handover (price at accept, pending/paid, reports, public Collected step) ([fbd5b56](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/fbd5b56dad273b119245f0100717590721cb38c5))
* **printing:** submitted/started emails + route notifications to contact_email ([0b9e085](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/0b9e08591dd17d22160f959ec2f4c6e5deb59723))
* **procurement:** per-makerspace To-Buy list (role-tagged hardware/printing, CSV export) ([7be3a26](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/7be3a26a200686c0d2dbac89a6b021582a28f4d7))
* public 3D spool/bucket UX + self-checkout scanner, 7-day login session, API-key request flow, Django admin parity ([90edf48](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/90edf48545a02096da92fb7d9c4985cd100c7ba7))
* public self-checkout + inventory-manager role; fix review P2s (lock products, validate makerspace, slug lookup precedence) ([9b10a44](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/9b10a4476980a5be1c86560286ed80f8e7e596aa))
* **public:** category sidebar (Popular/Most used/categories) + filtering on public catalog ([a6bd6da](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/a6bd6da55d476c56695cdd386508ce458c1bb7c9))
* **public:** inline map link, tighter header, bigger makerspace wordmark ([41ac3f7](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/41ac3f706515d51eba30c470ab0ffd946f341d4b))
* **public:** InvenTree-like catalog - side rail, denser grid, sticky tabbed actions ([7f27e5b](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/7f27e5ba307c20e912a9375f3a2a0727c9ffdb3f))
* **qr:** bulk ZIP download of QR batch as captioned SVGs (dependency-free); remove A4 print option; wire frontend Download-all button ([6651be9](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/6651be9840650f807f7bffda0cac128d31b20725))
* **qr:** cross-makerspace individual-asset move via rebind [asset-move phase 1: backend] ([4f0a6bc](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/4f0a6bcf6072184a11a1dfa7b2f0fa1f548315f6))
* **qr:** rename + rebind saved QR across makerspaces (superadmin) + batch docs ([e331dbb](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/e331dbbdd3037ebac687d467525767174fd4b835))
* **qr:** scanner UI to move an asset QR to another makerspace [asset-move phase 2: frontend] ([d6e7830](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/d6e7830a7b0c42aa134b471dc0a0db7d3ceec0b1))
* reject-broken at handover + to-be-fixed shelf, email print status, dark-mode fix ([c371d6e](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/c371d6e25f7dc618e3d100ded56fa02a3e84261b))
* **reports:** print-manager-only 3D reports + status/brand pie charts + most-used-brand ([e795661](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/e795661a745ef3dc7bc3b2695caa32c78c17da91))
* **scanner:** staff Scanner tab with camera resolve + QR revoke + box contents ([e0403e9](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/e0403e9e1a527e0b0f97710634290e2c8dfcfae1))
* **self-host:** one-command setup scripts + nginx admin/static proxy; maker+ops docs; remove internal docs from repo ([1d868b2](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/1d868b241bbb461a63e4fad48a3e0be3ad312cb1))
* serialized per-unit handout enforcement for individual-mode products ([def09dc](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/def09dcecb1e869e3095a202efa62474910b8b2f))
* **smtp:** per-makerspace implicit-SSL (port 465) option, mutually exclusive with STARTTLS ([d85dc3c](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/d85dc3c41c66ae70d6e9c2de05b34698e3076fed))
* **staff-ui:** reports dashboard+charts, ledger, users CRUD+makerspace create, cross-makerspace transfers, audit pagination, API-secret copy, status stepper, forced password change ([d11fc70](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/d11fc70acd412ce9286b96c90f6dcc671c241c99))
* **staff:** human-readable requester labels across reports/queues + OSMM badges ([a8253d6](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/a8253d6ed755292472d5bc5494c32d24ac2890ea))
* **staff:** printer/spool CRUD, QR batch w/ per-unit assets, CSV/XLSX bulk import, inventory qty adjust, queue modals ([ed6a20e](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/ed6a20e2c16844b8ca2d78a1333bc5be2e33891c))
* **staff:** superadmin picks a makerspace to operate before the console loads ([03bf371](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/03bf371ce2f8d451915670ec6bb6e1b0f346e504))
* **stats:** per-makerspace public-stats toggle + respect hidden availability counts ([8398747](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/83987477f199b390c0723ce144c7e81092252cd1))
* **stats:** public per-makerspace stats endpoint + OpenAPI ([a934f0f](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/a934f0ff039f8137713c549ac35eb69195e5103a))
* **stats:** public stats assembler + email-safe name resolver ([aa08b84](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/aa08b84459e4a01183f380e4c810634b40c0d86e))
* **stats:** public stats page ([7ab4d18](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/7ab4d189952bcd89e30213a0406b2d9b181fc61a))
* **stocktake:** count-entry UI wiring count-lines + variance table (was dead before) ([860e90e](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/860e90e112ee04ef9326afdb60b2912b966c9d30))
* **transfers:** allow intra-makerspace moves for EDIT_INVENTORY; cross-makerspace stays superadmin ([44f84fe](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/44f84fe09585a25bc639b193aaf0a5542b0d9b09))
* **transfers:** true makerspace-&gt;makerspace stock movement (deduct source, credit find-or-create destination product, dual audit; reject individual-tracked) ([bbea13c](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/bbea13c3765a055b3b123fc69b6e8b59a69bffb9))
* **ui:** migrate Inventory panel to DataTable/FilterBar with item detail drawer ([273b688](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/273b6881d709154ce8ac284a29ed66a94be8e06e))
* **ui:** OSMM branding polish + pastel stat boxes + drop docs/brand reference ([d194780](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/d1947804bcd1bf0b7054bfd0b4e9356f4493f14f))
* **ui:** OSMM README banner + hide QR payload in UI + responsive scanner + per-makerspace report leaderboards ([47b71a9](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/47b71a9469f30a7124ea36ed6e6da7dff4f93e05))
* **ui:** pastel notebook theme foundation — fill/ink tokens + soft shapes [reskin phase 1] ([fb620fc](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/fb620fc63530db7c6c8fbe3eabc9a6e27802d586))
* **ui:** pastel reskin final pass — stats page + whole-app contrast gate green [reskin phase 4] ([930e2a0](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/930e2a094f9a2e02ba9df259436823230bb507d9))
* **ui:** pastel reskin of public surfaces — steppers, cards, forms, auth [reskin phase 2] ([4ad942f](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/4ad942f933c42c17342e9124df6133ab5d6c12ec))
* **ui:** pastel reskin of staff console — panels, charts, shared primitives [reskin phase 3] ([476334d](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/476334da77c485af9c46c5ed6ed82ee874d0e03c))
* **ui:** reusable staff-console primitives (DataTable, FilterBar, bulk/status/empty/drawer) ([a62564f](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/a62564f4d9dff0a29f9584729e102161579ed675))


### Bug Fixes

* **admin:** scope CSP 'unsafe-eval' to /admin/ so Unfold's Alpine initializes ([7cf1ede](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/7cf1ede3de9721ac67f506e7bd5b4929fb355559))
* **audit:** phase 2 stock integrity ([05010cc](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/05010cc30a18312965cd79b8d4c96e9daef1fd6b))
* **audit:** phase 3 backend reports and reminders ([2a1e8b9](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/2a1e8b9c29b57ed416f42bd8b81be5176f6f6ac6))
* **ci:** sync frontend lockfile with license field (npm ci); don't fail-fast the image matrix ([a430d7b](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/a430d7bbd6f80cc51d8dbc73e06241d5f486ff92))
* close handoff evidence and staff ux gaps ([9ea344c](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/9ea344c8ec385e2c5e43caa1c38595691f9ff1bd))
* **direct-handout:** staff QR handout drops public flags, reject individual product-QR, container guards + issued-by ([a4acab5](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/a4acab5d923e9b8cc64b662e50d9230a4f0ee511))
* **directory:** restore whole-card click to catalog via stretched link (map link stays clickable) ([112fd59](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/112fd59ae76a07d93535955fc9ae5885377c4f9d))
* **docker:** frontend healthcheck uses 127.0.0.1 (IPv6 localhost was refused) ([c335836](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/c3358369f304f5ed3bc2bd5c5b63b996bd648c3c))
* **docker:** point published-image refs to ghcr.io/osmm-hq namespace ([460a731](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/460a731f330615e3a2449c96481d4a5437f7f1a8))
* **docker:** strip CRLF from frontend entrypoint + drop failing MinIO cors set ([3ac8cc8](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/3ac8cc877f0f43aca36c54a4ad33b5e8e2b18eec))
* **docker:** strip CRLF from frontend entrypoint + drop failing MinIO… ([14ae668](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/14ae66813ef101f4ffb34b00e8cdc0cc705ccc6f))
* **email:** clarify is_active toggle = custom-vs-default (email always sends), not suppression [stage-4] ([96399d7](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/96399d73ef20ebeac6b38704889f4f33609be5ed))
* **email:** pass staff HTML body, validate preview (400 not 500), gate templates tab to edit roles [stage-4] ([fb80a2e](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/fb80a2e49fcf292be820bce30ac0437363d515dd))
* **integrations:** Telegram test-alert returns delivered:false+detail instead of 500 ([4e9d3d9](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/4e9d3d90ca841816171af0a9801770bd92d48626))
* **inventory:** add staff needs-fix shelf moves ([ab4b6aa](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/ab4b6aa3b7172519b05f1b9ad5ef1d19f71bf653))
* **inventory:** reconcile individual asset fix counts ([6707d60](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/6707d60b2bd680288d45785e94af52bc347f1897))
* **inventory:** support individual asset fix moves ([d3cd13c](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/d3cd13cc42d1c2b823b30b57a1fcb3459601eb1a))
* **loans:** stage-4 review — empty-container guard covers child boxes + container list page_size ([f25007c](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/f25007c98809c4c6eb6f2640694dd31b4b90a4ca))
* **manual-print-log:** reject inactive printer + non-positive grams (DB constraint), tenant-first fetch, invalidate report cache ([7a8c1ef](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/7a8c1efdd67647d0f6435cbd2a8bab2132ab8889))
* **openapi:** resync snapshot+client with procurement endpoints; align to-buy quantity minimum ([51f94d7](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/51f94d7cd44d96f298fe59054048430de0b7c051))
* **printing,handout:** zxing fallback on native QR failure; filter direct-loan products; wire public-form honeypot ([10057f3](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/10057f3bc59ee89b04e0eead7c104a5ff97f788a))
* **printing:** guarantee STL/model downloads carry a file extension ([70352e7](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/70352e7e11cf344c801f1474b35a0d163c9a281c))
* **printing:** prefetch request files (no N+1); drop stale source container on cross-space transfer ([46d97d8](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/46d97d8f52b921f2ac44da293d688b8f9399c7dd))
* **qr-rebind:** guard source QR type on cross-makerspace, lock+savepoint 409, IsActiveStaff, scoped picker + permission gate ([a95d00f](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/a95d00fe8de726adfabf7b95529818065c44f0fd))
* **qr:** link unit qrs to inventory assets ([6a4d3dd](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/6a4d3dd59d2fda8daf6e1fb10fb069fdb3a555a5))
* **qr:** render namespaced standalone SVG for QR labels so the image isn't broken ([0dd562c](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/0dd562c1c17bc88f3adb8883f6f59ff9904e5502))
* **qr:** replace duplicate batch labels ([5c1c4ee](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/5c1c4ee452123b1675392e9479b972251707f1d1))
* **qr:** reprint existing unit labels ([defe311](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/defe3110df97d552f56b714a83f7146f9c11c701))
* **qr:** select inventory qr mode automatically ([9a6dca7](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/9a6dca7be49a0c635ca850d0acd92691888d3ec1))
* reconcile EmailLog index name with model state ([2f0ad01](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/2f0ad017745b73990a50f9543d8ae92f0584db46))
* **review-2:** ledger reports per-item (no bundled-loan undercount) + xlsx export strips tz-aware datetimes ([ca023f0](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/ca023f0eaeb3004f13aef87133cd05c6ac3b10be))
* **review-3:** apply must-change gate to all admin permission helpers, honest cross-makerspace transfer copy, ledger source schema includes direct_handout ([3a1f226](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/3a1f226c23aa2575ff51e35096e50ce4965535ca))
* **review-4:** block must-change accounts from Django admin + blacklist outstanding refresh tokens on password rotation ([6a73a0d](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/6a73a0dbd75ca32e032e014c0ae63ab885c70fa1))
* **review-5:** disable protected staff queries while password-change gated + invalidate on rotation ([ce61408](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/ce6140855eb345a3bf100c7843c2e6a2c67d72bd))
* **review:** enforce must_change_password gate on protected API, correct printing-report path, require staff password, role-superadmin UI, intra-only dest container ([8d78c6d](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/8d78c6db7051b9a084a92e74bd796ae79e63e770))
* **scanner:** render QR scanner via portal + harden camera open + self-host zxing wasm ([ad37b5b](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/ad37b5b0953d0e3a13bf454af780f6234005d788))
* **staff:** declare canManageMakerspace before allowedTabs (TDZ ReferenceError) ([26ac633](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/26ac633ed86b386e1fae66f0df8e762f8ee5db9b))
* **stats:** include accepted print jobs in queue + status counts ([7333e2f](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/7333e2fc393449a99fb1d77dd28595cddee1b2e9))
* **stats:** mask separated-digit phones + exclude hidden-availability items from current loans ([4191d15](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/4191d158964fbb3ff978dcaeb9b36d55e06acf9f))
* **superadmin-hide:** close print-list + needs-fix list leaks when unfiltered; payment totals count only completed/collected ([5cb5e47](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/5cb5e473a811767836d6b01aa7cf4e03dda405a3))
* **transfers:** reject cross-makerspace credit onto individual-tracked destination product (no phantom units) ([4297658](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/42976582b15e7004b43e481bb9b145a01777b077))
* **transfers:** surface DRF field errors readably + flag source-container ignored cross-makerspace ([26016ba](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/26016bafe520fff9c03eb0ceed062351efabf2fd))
* **ui:** dark-mode readable standalone colored text — split on-fill ink from theme-adaptive text [reskin stage-4] ([d35f7cb](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/d35f7cbad8e2481185ae49230a95035feebd743f))
* **ui:** link staff header to public inventory ([73b5371](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/73b53713eb392ee0c451ba3e2549b25a5ddc3e23))
* **ui:** open asset picker for individual fixes ([69ebe97](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/69ebe97b793205a52bb86fcd8823aa98b341282d))
* **ui:** phase 4 mobile settings polish ([3a55e06](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/3a55e0697846ce8b629d29cce97ecdf6b0ea3b8b))
* **ui:** rename archived restore action ([12a7752](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/12a7752f48ce1d54b9de085ab8ce8a18a787ce95))
* **ui:** show archived inventory state ([e795a26](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/e795a260b520db70f40140c1a6f53484895e5096))
* **ui:** show unit qrs in inventory ([2b00e08](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/2b00e0860eadd4e0acbbffd9a7cff9a3f04005ff))
* **upload:** resolve F-01 image upload validation ([17b1cf3](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/17b1cf36e8a14889524be12ddbd11724d160ea01))


### Performance Improvements

* composite indexes on hardware/print/ops/scan hot paths (lean-prod B1) ([21be922](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/21be92213fcb1aea0e0c04a283b4f8b149369932))
* kill direct-loan-items + box-QR N+1s via prefetch/annotation with fallback (lean-prod B2) ([e90cf13](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/e90cf1374057da7f39f5d6db975a54129a1cd2b6))
* PrintPrinterSerializer reads filtered prefetch (to_attr) with query fallback (lean-prod B2) ([f7b08bb](https://github.com/OSMM-HQ/OSMM-Makerspace-Manager/commit/f7b08bb8b33f951a915acf50cc238f68b8b3a427))
