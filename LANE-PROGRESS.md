# Research Wave 0: events and bookings

## Completed
- Read AGENTS.md, global Claude rules, DEV-WORKFLOW, relevant invariants and research D1/D3.
- Added member-owned and staff-authorized registration cancellation routes, schemas and staff origin scoping.
- Reused the transactional cancellation service for audit, pending-charge release and FIFO promotion; added its locked module check.
- Exposed public event amount and host currency, including organization catalogues.
- Added member cancellation controls and staff roster actions. Mutations refresh activity/availability/payments or staff roster/count/eligibility/payment caches.
- Added free/paid pricing displays in makerspace and organization public event cards.
- Added backend regression tests and five Vitest files; updated the strict public-field leak guard.
- Verified every touched source/test file stays below 300 lines; no split was needed.
- Verification: five targeted Vitest files / 14 tests passed; TypeScript `tsc --noEmit -p tsconfig.json` passed; changed Python files parsed with `ast`; `git diff --check` passed.

## Remaining
- Coordinator must run the database regressions below and review/QA the lane. No database tests were run here.
- Coordinator must regenerate OpenAPI snapshot and generated TypeScript, then verify the combined lane. Neither generated file was edited here.
- Changes remain unstaged; no git state-changing commands were run.

## Tests added / changed
- `backend/tests/events/test_registration_cancel_api.py`: real pending-charge cancellation, FIFO promotion and human audit attribution for both routes; pending/waitlisted cancellation without presence/new waiver; terminal conflicts; ownership/email/cross-tenant denial; restricted/revoked account guards; legacy NULL provenance; invalid body/module-off refusal; locked service module gate; collaborative provenance after removal and host module gate; approval-only manual promotion and settled/waived payment retention; route schemas and origin scoping.
- `backend/tests/events/test_public_event_price.py`: paid/free decimal amounts and configured currency without secrets; charging-default currency without creating settings; organization catalogue price and host currency.
- `backend/tests/events/test_public_event_leaks.py`: expanded only the explicit public allowlist with `payment_amount` and `currency`.
- `frontend/src/features/inventory/PublicEventsPage.test.tsx`: free/paid price before registration and price beside an approval form.
- `frontend/src/features/organizations/PublicOrganizationPage.test.tsx`: host currency/free price in organization cards.
- `frontend/src/features/members/MemberEventCancel.test.tsx`: all live states, terminal controls hidden, pending button guard, conflict retry, cache refresh.
- `frontend/src/features/staff/EventRegistrationRoster.test.tsx`: live/terminal row actions, selected registration ID, pending/error row behavior.
- `frontend/src/features/staff/eventsRegistrationApi.test.tsx`: staff route/body and cache refresh.

Coordinator command: `./scripts/dev.sh test tests/events/test_registration_cancel_api.py tests/events/test_public_event_price.py tests/events/test_public_event_leaks.py tests/events/test_registration_policy.py tests/events/test_admin_api.py tests/events/test_services.py tests/events/test_event_checkin_member_p14.py tests/events/test_event_collaboration_scope_p14.py tests/events/test_event_calendars.py tests/organizations`.
Frontend command: `npm test -- src/features/members/MemberEventCancel.test.tsx src/features/staff/eventsRegistrationApi.test.tsx src/features/staff/EventRegistrationRoster.test.tsx src/features/inventory/PublicEventsPage.test.tsx src/features/organizations/PublicOrganizationPage.test.tsx`.

## Coordinator checks
- Database tests cannot run in this sandbox; test files will be listed here when written.
- OpenAPI snapshot and generated TypeScript regeneration are coordinator-owned.
- Local CLI review gate unavailable: codex doctor fails configuration/home resolution and provider connectivity.
- Existing frontend dependencies were copied into this worktree's ignored `frontend/node_modules` for verification; no main-checkout files were edited.

## Deferred owner decisions
- D2: booking presence requirement remains unchanged.
- E7: paid-cancellation re-registration semantics remain unchanged; owner must decide fresh registration versus refusal.
- No migrations, new models, module keys or feature keys are needed for D1/D3.
- No additional out-of-scope defect was found. E7 remains the research's known defect: reviving a registration reuses its terminal payment and cannot create a new charge. Refund behavior was not extended.
