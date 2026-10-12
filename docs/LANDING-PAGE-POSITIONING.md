# SpaceWorks landing-page modules and positioning

Companion to the [feature inventory](LANDING-PAGE-FEATURES.md).

## Optional modules: landing-page comparison source

This table contains the **29 non-core modules counted from the registry**. “Default-on” still means optional:
an operator can disable it. Every other row is opt-in. The six core modules are omitted because there is no
supported installation without them.

| Optional module | What it adds | What you lose without it |
| --- | --- | --- |
| Asset units | Individually QR-tracked units and per-unit status | Quantity lending still works, but the exact physical unit and its label are unknown |
| Containers | Nested boxes, shelves and rooms, plus container moves | No editable location hierarchy or container selection during direct handout |
| Bulk import | Spreadsheet upload, column mapping, preview and commit | Products must be created individually or through the API |
| Stock transfers | Recorded movement within and between makerspaces | No supported cross-tenant stock movement workflow |
| QR print batches | Printable sheets and downloadable ZIP batches | QR codes print only one at a time |
| Guest handover | Narrow front-desk issue, direct-handout and return console | Handovers remain possible in the full staff console |
| Procurement | To-buy list, receipts and conversion of purchases into stock | Purchasing is tracked outside SpaceWorks |
| Stocktake | Scan-first count sessions, variance and ledger adjustment | Counts are corrected directly, without a stocktake session or variance report |
| Machines | Machine registry, operators, documents, usage, warranty and consumables | The machine side of the product disappears |
| Machine service | Member job requests, staff queue, files, consumption and usage | Machines remain records, but SpaceWorks does not manage work on them |
| Printing | Print-specific request intake, files and queue views | 3D printers can use the generic service queue, without print-specific handling |
| Maintenance | Preventive schedules, completed-maintenance logs and files | No in-app maintenance schedule or history |
| Events | Public events, registration, staff registration, QR check-in and collaboration | No event listing, registration, attendance history or event payments |
| Bookings | Resources, booking rules, staff booking and public self-booking | No time-slot reservation workflow or booking payments |
| Membership | Join requests, waivers, referrals, profiles, directory and activity | People can still borrow, but enrolment and community features disappear |
| Notifications | In-app inbox and unread state | No in-app alerts; separately installed outbound channels can still send |
| Email | Makerspace email through its SMTP account | No tenant email; platform recovery and verification mail still sends |
| Telegram | Group alerts and test delivery | No Telegram alerts |
| Slack | Slack incoming-webhook destination | No Slack notification surface |
| Mattermost | Mattermost incoming-webhook destination | No Mattermost notification surface |
| Discord | Discord incoming-webhook destination | No Discord notification surface |
| Signed webhooks | HMAC-signed outbound event deliveries to an operator-chosen URL | Integrations must poll the API instead of receiving events |
| Reports | Dashboards, ledger, registered reports and CSV/XLSX export | No analytics or report-export screens |
| Payments | Stripe/Razorpay checkout, charges, receipts and reconciliation | Money is handled outside SpaceWorks |
| Member accounts | Self-sign-up, member area, password, Google/Apple and phone login | Staff sign-in and external OIDC remain; members become staff-created walk-ins |
| Mobile apps | Attested device sessions, native push and PaymentSheet support | The web app works, but native clients cannot hold a session for the space |
| Connected devices | Printers and label printers enrolled with an Ed25519 key; signed heartbeats, key rotation/revocation, printer jobs, label commands and offline alerts | No device enrollment or device-signed requests |
| Backup & custody (default-on) | Makerspace archive requests and downloads, archive-recipient keys and custody status | Deployment backups still cover the space; a Space Manager cannot request or open its own archives |
| Updates (default-on) | In-app version checks and controlled software updates | Updates must be run through host tooling or an external deployment pipeline |

Two dependency rules also come directly from the registry: Printing requires Machine service, and Mobile
apps requires Member accounts. Installing a dependent module pulls in its requirement; a required module
cannot be removed while its dependent remains installed.

## Customer-controlled feature switches

Modules are whole product areas controlled by a superadmin. Space Managers also have narrower switches:

| Feature switch | What it controls | Default |
| --- | --- | --- |
| Payments master | Whether any online payment area can operate | On |
| Machine payments | Charges for machine jobs | Off |
| Booking payments | Charges for bookings | Off |
| Event payments | Charges for event registration | Off |
| Membership payments | Membership dues | Off |
| Native push | Push delivery to connected native clients | On |
| Inventory self-checkout | Member self-checkout and staff direct handouts | On |
| Presence geofence | Advisory location check at check-in | On |

An “on” switch is still inert when its parent module or required provider credential is missing.

## Who it is for

- **Makerspaces and community workshops** that lend shared tools and need evidence-backed accountability.
- **Fab labs** that combine inventory, machine work, 3D printing, maintenance, events and bookings.
- **Tool libraries** that want the full lending lifecycle without installing machine operations.
- **Universities and institutional workshops** that need their own identity provider, organization-wide
  staff authority and multiple spaces on one deployment.
- **Networks, chains and hosting partners** that operate several isolated makerspaces while coordinating
  selected staff and cross-space stock movement.
- **Independent spaces with walk-in communities** that want attributable handovers without requiring every
  visitor to maintain a SpaceWorks account.

## Deployment options

### Self-hosting

Self-hosting is the primary documented deployment model. A first-run wizard for macOS/Linux and Windows checks
Docker, generates secrets, writes configuration, builds the stack, creates the first administrator and
makerspace, and prints the URL and credentials. Prebuilt backend and frontend container images are also
available. PostgreSQL, Redis, S3-compatible storage, background workers and migrations use Docker Compose.

The Updates module can check and apply releases from the control plane. Guided updates are backup-first,
run readiness checks and can return application containers to the retained prior release if deployment
fails.

### Managed or partner-hosted operation

One SpaceWorks deployment can host many isolated makerspaces, so an institution, network or nearby partner
can operate it as a managed multi-tenant service. A deployment may also use managed PostgreSQL. The
`cloud` install profile selects the module set intended for a hosted box, and the tenant-migration workflow
lets a hosted space later move to its own server.

**Honest limits:** the shipped repository documents the managed-hosting architecture and a pilot-oriented
managed-PostgreSQL path; it does not document a first-party SpaceWorks hosting service. The documented free
tier is suitable for demos or pilots, not dependable production.

## Genuine differentiators

- **Evidence-backed handovers, enforced rather than suggested.** Photos, scans, remarks and audit entries
  are prerequisites of the lending workflow, not fields staff may forget to fill in.
- **One workflow regardless of interface.** Web staff, front desk, self-checkout and Telegram actions all
  reach the same state and inventory controls.
- **Per-makerspace encrypted integrations.** Each tenant owns its notification credentials; secrets are
  encrypted at rest, write-only and absent from frontend bootstrap data.
- **Modules that can be installed, hidden, restored and deliberately purged.** Uninstall retains history;
  destructive deletion is a separate confirmed action; selected unused apps can even be removed from a
  deployment's runtime surfaces.
- **Tenant data ownership and a real exit path.** Spaces can export data, move rows and files in an
  encrypted archive, approve which personal details travel, and cut over without two writable copies.
- **Multi-space authority without flattening tenant boundaries.** Organizations can grant selected actions
  across linked spaces while each makerspace keeps its own staff roster, inventory and audit scope.
- **Useful without mandatory member accounts.** External identity and named walk-in records preserve
  accountability even when built-in self-sign-up is disabled.
- **Open source and self-hostable.** SpaceWorks is licensed AGPL-3.0-or-later and can run on infrastructure
  controlled by the community using it.

## Not yet shipped

These items must not appear as current capabilities in landing-page copy:

- **Direct hardware integration:** SpaceWorks does not yet read live job state from printers or CNC
  controllers, drive label printers, or control doors and access hardware. Machine queues are operated by
  people, and the presence geofence is advisory.
- **Invitation requests:** a prospective member cannot yet ask to receive an invitation. Staff invitation
  and membership-application paths are separate existing flows.
- **First-party native applications:** the server-side device-session, push and payment-sheet substrate
  exists, but native app clients themselves remain out of scope.
- **Google Sheets OAuth publishing:** this is out of scope; CSV/XLSX report export is the shipped
  spreadsheet path.
