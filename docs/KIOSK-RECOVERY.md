# Failed kiosk replay recovery — phase 9e

Failed attempts remain failed. Review appends resolution code, human reviewer and
time; the original fingerprint, state, evidence, failure and attempt timestamps
stay unchanged. No recovery endpoint mutates inventory or request/loan state.

The Requests panel lists retained failures under each operation's current RBAC
action, including custom and organization roles. Origin scope, hidden spaces,
archival and restricted/suspended users keep their normal denial semantics.
Historical review is independent of the kiosk feature and module switches:
turning off a channel does not erase its outstanding review obligations. Any
new corrective command still checks all current modules/features; disabled
requirements answer 400 through the normal replay protocol.

Acknowledgement requires staff to verify no physical change occurred. A replacement
must be a fresh succeeded replay of the same version/operation and known request
or loan, in a new aggregate, created/completed after the failed attempt. One success
resolves at most one failure. Identical review is idempotent; a conflicting second
review is 409. Both source and replacement coordination are locked in UUID order.
Review records `kiosk.replay_resolved` with a real User and channel/domain refs.

Corrections use the current Station session, a new authenticated operator lease,
an online-loaded work package and a new normalized photo. They persist in the same
encrypted queue as normal replay, preserving identity through uncertain delivery.
The original failed scope and evidence are retained. Reload can resume the saved
correction; staff explicitly links it only after server success. Errors leave the
source unresolved. Return correction offers all outstanding items as returned;
damage/missing outcomes continue through the existing staff return workflow.

Failed direct handouts have no retained borrower/items/subject identity, so automatic
replacement compatibility cannot be verified and linking fails closed. Staff can
inspect evidence and acknowledge only if they verified no physical change. A future
owner-approved identity contract is required to extend replacement to this case.
Direct returns derive missing subject identity from the retained predecessor chain.

Evidence IDs are operational references, not read authority. A server-calculated
permission flag hides previews without UPLOAD_EVIDENCE. The existing evidence endpoint
alone creates a short-lived URL, applies module/tenant/retention checks and audits the
read. A 410 is shown as expiry; no private key or URL is stored with review data.

Cleanup retains any succeeded replacement still referenced by a retained failure.
Expired failed leaves can be deleted before their protected replacements on later
bounded passes. Evidence rows survive coordination cleanup. Whole-tenant purge clears
both self-links before removing coordination. All four resolution fields and their
User edge are classified as source-local/omitted for portable tenant migration;
resolution audit domain refs remap while replay/session/lease UUIDs stay source snapshots.

## Coordinator validation

Run the new hardware recovery/scope/concurrency/contracts tests plus existing replay,
origin, data-export, catalog/reference and purge tests in the isolated Postgres runner.
Regenerate OpenAPI schema and frontend client artifacts; the lane leaves these alone.
Run `scripts/dev.sh e2e`: it seeds separate immutable tenants, builds production assets
and runs serial Playwright on a spare preview port (5173 by default), against the real
Docker backend/Postgres/Redis/MinIO. Existing dev port 5000 remains untouched. Preview
API requests use Vite's inherited API proxy; the dev backend already admits 5173.
If the preview port changes, admit its exact origin on the backend and MinIO CORS.

The dev backend must already have a valid API_CLIENT_ENC_KEY and a minimum 32-byte
EVENT_STATION_PIN_PEPPER configured, just as live Station services require. Seeding
does not manufacture different secrets for a process that cannot serve them. The
Station PIN and public bearer token are written only to the ignored `.seed.json`,
never seed stdout. Verify the backend mount is the coordinator's integrated tree
before trusting Playwright. Backend/e2e tests were authored but not run in this lane.
