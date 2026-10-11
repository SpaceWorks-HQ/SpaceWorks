# Lane w5-public

Complete: public item deep links and client-side metadata; member portal tabs;
filterable event agenda/month and bookable-space discovery. All changes unstaged.

Read AGENTS.md, global workflow, DEV-WORKFLOW, frontend-ux sections 1/3/4/5/6,
index Wave 5, and relevant public exposure, colour/accessibility and event invariants.

## Completed

- Item routes: `/m/:slug/items/:itemId` (central) and `/items/:itemId` (single).
  Numeric IDs and optional readable suffixes resolve to the existing detail API;
  canonical URLs use the numeric identity. Catalogue titles link to item pages;
  Quick view remains available. Detail uses only existing public fields.
- Existing DRF detail view still uses `PublicProductSerializer`. Private, archived,
  other-tenant and missing items have an identical 404 body. Disabled module = 400;
  edition/public-site hiding remains 404. Error responses documented in spectacular.
- Client-side title, description, canonical, OG title/description/url/image/type/site
  tags for catalogue, items, events and bookings. Head tags deduplicate and restore
  on navigation; bootstrap branding cannot overwrite a routed item's title.
  Events/bookings edition homes retain the home URL as their canonical URL.
- Member overview/loans/bookings/events/payments/inbox/account tabs, deep links,
  arrow/Home/End keyboard navigation, module-aware visibility and a skip target.
  Reuses existing queries, panels and mutations. Payments still work for borrowers
  with no membership or rail module; Inbox uses personal derived activity notices.
  Cached activity is hidden when its membership gate closes or refresh is refused.
- Event search, free/open-registration filters, month selection and list/calendar
  toggle persist in URL parameters. Calendar links focus the existing event cards;
  registration forms and ICS downloads stay in place.
- Bookable-space search/kind filters, list/calendar toggle and published busy
  intervals reuse existing space/availability APIs and booking forms. No inferred
  free slots or hidden names. Past months are not queried. A 31-day DST-fallback
  month uses two bounded requests, deduplicates intervals and hides partial results.
- Existing w5-theme colour scoping and support/footer components are reused.
- No new model, migration, module key, feature key, package or generated API file.

## Verification

- Final Vitest run: **32 files, 125 tests passed**.
- `node node_modules/typescript/bin/tsc -b --pretty false`: passed.
- Python AST parsing of the changed view and new backend tests: passed.
- `git diff --check`: passed (Git reports line-ending normalization notices).
- Every changed/new file is below 300 lines. AGENTS.md and CLAUDE.md remain untouched
  and byte-identical. No staging, commit, checkout, reset, merge or other git mutation.
- Database tests NOT RUN: Docker/Postgres unavailable in the implementation sandbox.
- No production build or live-browser QA was run. Unit axe checks cover new item,
  calendar, member panels and keyboard tabs; real contrast/layout QA remains external.
- `codex doctor` reports unavailable configuration and unreachable inference in this
  sandbox; a separate CLI review is unavailable. Coordinator review remains required.

Final frontend command (from `frontend/`):

```text
node node_modules/vitest/vitest.mjs run src/AppRoutesPublic.test.tsx src/components/PageMetadata.test.tsx src/features/members src/features/inventory/PublicEventsPage.test.tsx src/features/inventory/PublicInventoryBranding.test.tsx src/features/discovery/PublicDiscovery.test.tsx src/features/bookings src/App.centralMemberRoute.test.tsx
```

## Tests added / updated

New backend file `backend/tests/test_public_item_detail.py` (coordinator must run):

- `test_detail_matches_public_list_serializer_and_visibility`: six mode/count-gate
  combinations; serializer/list parity, allowlist and private-field exclusion.
- `test_private_archived_cross_tenant_and_missing_have_identical_404`.
- `test_detail_module_off_is_400_and_reenable_restores_same_item`.
- `test_detail_disabled_public_site_and_missing_space_have_same_not_found`.

New frontend files:

- `AppRoutesPublic.test.tsx`: central/single item links; canonical numeric URL;
  missing/private UI + cleanup; malformed IDs; module off; member tab routes;
  events/bookings edition home canonical URLs.
- `components/PageMetadata.test.tsx`: complete head tags; bootstrap title ownership;
  duplicate/update/unmount cleanup; executable URL rejection and literal markup.
- `features/members/MemberPortalTabs.test.tsx`: both route bases + Back; keyboard
  arrows/Home/End/roving focus + axe; hidden modules and account-only payments.
- `features/members/MemberAreaPortal.test.tsx`: isolated loans/bookings/events panes;
  no-membership payments; derived inbox and Account profile + axe; signed-out deep
  link sign-in; cached notice suppression when the membership module turns off.
- `features/discovery/PublicDiscovery.test.tsx`: event search/free/month deep links
  and calendar links + axe; URL/Back restoration; space/kind filtering + form reuse;
  busy calendar/name privacy + axe; no hidden-availability query.
- `features/bookings/SpaceDiscoveryCalendar.test.tsx`: DST bounded-window requests
  and deduplication; no partial results after failure; no past-window requests.

Updated existing tests: PublicInventoryBranding (home head tags), MemberArea
(Account navigation), MemberAreaAdmission (Payments navigation), MemberAdmission
(updated payment guidance).

Coordinator backend command (from repo root, isolated runner):

```text
./scripts/dev.sh test tests/test_public_item_detail.py tests/test_end_to_end_prd_gaps.py tests/modules/test_combo_editions.py tests/test_apiclient_scope_registry.py
```

Coordinator must regenerate OpenAPI snapshot/client, review, perform browser QA and
handle staging/commits. Nothing remains to implement within the assigned lane.

## Deferred / owner decision

- Server-side OG delivery (edge/nginx injection versus SSR/prerender) needs the
  owner's choice. No nginx, prerender, server meta delivery or crawler guarantees.
- Inbox uses existing notices; recipient inbox models and notification preferences
  belong to the larger notifications programme, not this tab-reuse lane.
- Item gallery/specs and slug-only identity require public API/model fields that do
  not exist today; this lane uses the existing image/category/description allowlist.
- Event hero routes, slot-selection grids, recurring bookings and machine live boards
  are broader research items outside this assigned discovery-view scope.

## Implementation findings (resolved in the review pass below)

- Public catalogue `apply_q` uses `search_vector`, whose trigger includes private
  `storage_location` (`backend/apps/inventory/migrations/0010_inventoryproduct_search_vector.py`).
  A visitor may infer storage locations through search matches despite safe response
  serialization. Fixed in the review pass with a public-only query vector.
- Existing public inventory list/category gates raised 404 for module-off conditions.
  Fixed in the review pass so all three inventory surfaces follow the 400 contract.

## Complete file manifest

Created:

- `LANE-PROGRESS.md`
- `backend/tests/test_public_item_detail.py`
- `frontend/src/AppRoutesPublic.test.tsx`
- `frontend/src/components/PageMetadata.tsx`
- `frontend/src/components/PageMetadata.test.tsx`
- `frontend/src/features/bookings/SpaceDiscoveryCalendar.tsx`
- `frontend/src/features/bookings/SpaceDiscoveryCalendar.test.tsx`
- `frontend/src/features/discovery/DiscoveryControls.tsx`
- `frontend/src/features/discovery/MonthCalendar.tsx`
- `frontend/src/features/discovery/useDiscoveryState.ts`
- `frontend/src/features/discovery/PublicDiscovery.test.tsx`
- `frontend/src/features/inventory/PublicItemPage.tsx`
- `frontend/src/features/members/MemberPortalTabs.tsx`
- `frontend/src/features/members/MemberPortalTabs.test.tsx`
- `frontend/src/features/members/MemberAreaPortal.test.tsx`

Modified:

- `backend/apps/inventory/views.py`
- `frontend/src/AppRoutes.tsx`
- `frontend/src/lib/branding.ts`
- `frontend/src/features/bookings/PublicBookingsPage.tsx`
- `frontend/src/features/bookings/publicBookingsApi.ts`
- `frontend/src/features/inventory/ProductCard.tsx`
- `frontend/src/features/inventory/PublicEventsPage.tsx`
- `frontend/src/features/inventory/PublicInventoryPage.tsx`
- `frontend/src/features/inventory/PublicInventoryBranding.test.tsx`
- `frontend/src/features/members/MemberArea.tsx`
- `frontend/src/features/members/MemberActivity.tsx`
- `frontend/src/features/members/MemberAdmission.tsx`
- `frontend/src/features/members/MemberArea.test.tsx`
- `frontend/src/features/members/MemberAreaAdmission.test.tsx`
- `frontend/src/features/members/MemberAdmission.test.tsx`

## Review pass

Completed 2026-10-11. Read the lane brief, handoff, AGENTS/global workflow,
DEV-WORKFLOW, relevant invariants, all tracked diffs and untracked source/tests.
No staging, commits or other git mutations were performed.

Defects found and fixed:

1. **Public search exposed private-field matches.** The shared trigger vector
   includes storage locations and tracking mode. Public catalogue queries now build
   a name/description-only SearchVector and pass it to the existing search helper.
   Staff search retains its existing vector. Added positive prefix/phrase/typo tests
   and private-field inclusion/exclusion search regressions.
2. **Inconsistent module-off responses and hidden-site gate precedence.** List and
   category views now use the same edition/module guard as detail (400 when off,
   404 when edition-hidden). Public-site hiding is checked before the module gate,
   so a hidden site's disabled module cannot reveal its existence. Added gate,
   archived/importing/aborted tenant and edition tests.
3. **Incorrect and stale OpenAPI.** The module validation response is an array of
   strings, not a string. Corrected its serializer, documented all list/category
   errors too, updated both aliases in the snapshot and regenerated api.ts from
   that snapshot. Added a focused schema-generation regression. Snapshot changes
   were applied locally; live spectacular regeneration/verification needs Django
   and remains a coordinator check.
4. **Tenant slugs broke member tab navigation.** Splitting at the first '/member'
   misparsed slugs such as 'member' and 'member-tools'. Anchored route matching now
   preserves the tenant slug and excludes invalid tab names from the link base.
   Added deep-link, Back and invalid-tab regressions.
5. **Discovery used device-local calendar days.** Month boundaries, filters,
   calendar cells, interval labels and current-month defaults now use the bootstrap
   makerspace timezone. Added calendarDates.ts with zone-aware boundaries, real
   Europe/London DST tests, skipped-midnight coverage and Asia/Kolkata month-edge
   discovery/calendar tests. The DST request test now uses the real zone rather
   than a mocked month boundary.
6. **Cached personal data survived membership authorization failure.** Member
   activity, applications and referrals now require a successful membership read;
   a 401 also hides cached payments. Borrowers with a valid account and no
   membership still see their own charges. Added cached-activity/payment suppression
   coverage while keeping the existing account-only debt test.
7. **Refresh errors produced misleading empty-filter messages.** Events/bookings
   now suppress 'No matching' when a refresh fails. Added cached-data/error tests.
8. **Missing source-map documentation and CRLF files.** Documented new routes,
   metadata, portal and discovery ownership in docs/SOURCE-MAP.md. Normalized all
   touched text files to UTF-8 without BOM and LF; no mojibake found. Added a
   ProductCard regression for title deep links and retained quick view.
9. **Skip target broke the repository's tabindex contract.** The always-rendered
   member tab panel now uses tabindex=-1 and has a regression assertion.

Review verification:

- `python -m py_compile backend/apps/inventory/views.py backend/tests/test_public_item_detail.py`: passed.
- `npx.cmd tsc -b --pretty false` from frontend: passed.
- `npx.cmd vitest run src/AppRoutesPublic.test.tsx src/components/PageMetadata.test.tsx src/features/members src/features/inventory/PublicEventsPage.test.tsx src/features/inventory/PublicInventoryBranding.test.tsx src/features/inventory/ProductCard.test.tsx src/features/discovery src/features/bookings src/App.centralMemberRoute.test.tsx`:
  **34 files, 137 tests passed**, including the final gate/cache edits. The final
  skip-target assertion is also checked in the focused tab suite.
- `git diff --check`: passed. All touched application source files are below 300
  lines; generated schema/client files are excluded. AGENTS/CLAUDE are byte-identical.
- No new model, persisted field, migration, task, fan-out, object writer, environment
  variable or module key. Export/FK/migration authority catalogues and gate policies
  therefore need no new entries. Backend additions are reads; existing member
  mutations still use the same audited endpoints/services. Anonymous inventory
  stays scoped by the canonical public tenant lookup and servability predicate;
  no staff query was added or widened.
- Host Python has no Django. Docker API access is denied. Backend DB tests and live
  spectacular generation were not run. `codex doctor` still fails config loading
  and provider reachability; independent CLI review remains a coordinator gate.
- Server-side Open Graph delivery remains an owner decision. No server/prerender
  delivery was introduced. Live browser QA remains outstanding.

Coordinator must run (repo root, isolated Docker runner):

```text
./scripts/dev.sh test tests/test_public_item_detail.py tests/test_search_q.py tests/test_end_to_end_prd_gaps.py tests/modules/test_combo_editions.py tests/test_apiclient_scope_registry.py
```

Then regenerate OpenAPI with spectacular `--format openapi-json`, regenerate the
client, compare the targeted contract, and perform browser QA before integration.
