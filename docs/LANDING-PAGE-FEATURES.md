# SpaceWorks landing-page feature inventory

SpaceWorks is an open-source, self-hostable management platform for makerspaces and other shared
workshops. It brings the public catalogue, hardware lending, machine work, 3D printing, events, bookings,
membership, payments, notifications, reporting and operational records into one multi-makerspace system,
while keeping every physical handover attributable to a person and backed by evidence.

*Positioning: run the shared workshop from request to return, with proof of who handled what and when.*

## The core problem it solves

Shared tools move between shelves, boxes, members and volunteers. A spreadsheet can show a count, but it
usually cannot settle what happened when something comes back damaged, does not come back at all, or was handed out by a different volunteer.

SpaceWorks makes traceability part of the workflow rather than an optional note:

- A reviewed hardware request cannot be issued until staff scan a box QR code and attach an issue photo.
- Member self-checkout and staff direct handout require an eligible tool plus uploaded issue evidence.
- A return requires a return photo and a written remark.
- Issue and return photos, QR scan records and audit history are immutable or append-only.
- Lost or damaged items can close a request with an issue and connect the incident to the member's access status.
- Staff accept or reject requests in the staff console or `/control/` through the same controlled workflow; Telegram sends outbound alerts.

The result is a record of the whole handover, not just a number being decremented and incremented.

## Counted product shape

These counts were checked against the current sources rather than copied as marketing estimates:

| What was counted | Result | Source |
| --- | --- | --- |
| Module keys and customer-facing areas | **32 modules in 12 areas** | `backend/apps/makerspaces/module_registry.py` |
| Module modes | **6 core, 4 optional default-on, 22 opt-in; 26 non-core total** | `backend/apps/makerspaces/module_registry.py` |
| User-facing module entries | **32**, with no missing registry key and no extra entry | `docs/MODULES.md` |
| Seeded default roles | **4**: Space Manager, Inventory Manager, Machine Manager and Member | Roles table in `README.md` |

The six core keys counted in the registry are Public inventory, Request workflow, Staff admin, Evidence
uploads, QR management and Scanner. Custom roles can be added beyond the four seeded roles.

## Hardware lending and returns

- Publish a public, makerspace-specific catalogue with categories and item detail pages.
- Let authenticated members submit borrow requests and follow their status.
- Give staff a review queue for accepting or rejecting requests, then issuing, partially returning, returning or closing them with an issue.
- Prevent staff from issuing more than the accepted quantity unless they have explicit workflow
  permission.
- Support direct counter handouts and a deliberately narrow handover console for front-desk volunteers.
- Enable self-checkout and self-return for eligible QR-tracked tools when the space chooses to offer it.
- Keep staff-issued requests, direct handouts and self-service loans in the same evidence and audit trail.
- Track what is out, who has it and what is overdue; return reminders are available from the hardware
  request system.

**Honest limits:** public request submission is not anonymous; it requires an authenticated member. The public
catalogue can be made effectively empty by marking every item private, but the core catalogue and lending
workflow themselves cannot be uninstalled.

## Inventory and availability

- Manage products, categories, quantities and individually tracked asset units.
- Calculate available, reserved, issued, damaged and lost stock in one guarded availability service, with
  row-level locking and a rule that availability never goes below zero.
- Choose what the public sees for each item: an exact count, a simple Available/Limited/Unavailable label, no availability information, or no public listing at all.
- Model boxes and nested storage containers, including moves between locations.
- Import inventory from a spreadsheet with column mapping, preview and commit stages.
- Move stock within a makerspace or transfer it between makerspaces through a recorded sending and
  receiving flow.
- Run scan-first stocktakes, review variance, and commit the adjustment to the ledger.
- Maintain a procurement “to buy” list, attach receipts and move purchased items into stock.
- Generate printable QR sheets and downloadable label ZIPs in batches.

**Honest limits:** without the optional Asset units module, SpaceWorks tracks product quantities but cannot
identify which physical unit was lent. Without Stocktake, corrections are direct quantity edits rather
than a documented count session.

## QR codes and evidence

- Generate, print, revoke and rebind namespaced QR codes for boxes, products and individual assets.
- Scan with the web camera scanner and resolve a code to its container or eligible tool.
- Preserve an immutable scan history.
- Store issue and return photos in a private S3-compatible bucket and expose them through short-lived, permission-scoped links.
- Bind presigned uploads to an allowed file type and size range.
- Upload to a staging key first, then promote evidence exactly once. The client never receives write
  access to the final evidence object, preventing replacement through a still-valid upload link.

**Honest limits:** the shipped product generates printable files but does not drive a physical label
printer directly.

## Members, identity and access

- Offer username/password sign-in out of the box.
- Add Google, Apple, generic OpenID Connect providers such as Keycloak, Authentik, Azure AD or Okta, and phone sign-in with SMS codes.
- Switch password, identity-provider, phone-code and self-sign-up methods independently at platform level.
- Refuse login-method changes that would leave a person with no usable credential or lock every
  superadmin out.
- Run without the built-in member-account ecosystem: staff can create named walk-in records with no
  password, while an institution can continue to use its own OpenID Connect provider.
- Handle join requests, referrals, verification, waivers, memberships and member activity.
- Offer opt-in maker profiles with projects, interests, education and, when configured, a GitHub
  contribution count.
- Publish only profiles whose owners chose to appear in the member directory.
- Record presence and optionally perform an advisory geofence check.
- Restrict or suspend a member when accountability or access problems require it.

**Honest limits:** Google, Apple, OpenID Connect and SMS sign-in need credentials from the chosen provider;
only password sign-in works without external setup. Geofencing is advisory and never blocks entry. Changing
a login policy does not revoke existing sessions; restriction or suspension is the revocation path.

## Staff roles and permissions

- Scope staff access by makerspace and by action, not by a hard-coded role name.
- Seed four protected starting roles, then let a Space Manager rename or narrow them and create custom roles from actions the manager is allowed to grant.
- Give Inventory Managers the full hardware lifecycle without machine, staff or settings access.
- Scope Machine Managers to all machines or selected machines.
- Build a custom Front Desk or Duty Volunteer role that sees only request handover, direct handout and job
  collection surfaces.
- Block privilege escalation: a manager cannot grant an action they do not hold, and high-risk staff and
  stock-transfer actions remain superadmin-only.
- Provide a separate superadmin control plane at `/control/`, kept off the public frontend port. The normal
  staff console remains at `/admin`.

**Honest limits:** front-desk handover is not a fifth built-in role. It is an optional console paired with
a custom per-makerspace role, so each space must choose and assign the actions it wants.

## Machines, jobs and maintenance

- Maintain a machine registry with operators, images, documents, usage, warranty records and consumable pools.
- Accept machine service requests, collect uploaded job files and manage a staff work queue.
- Record which machine ran a job, who operated it, material consumption and the resulting usage entry.
- Narrow machine access per staff role rather than exposing every machine to every maintainer.
- Schedule preventive maintenance and record reactive work orders, logs and supporting documents.
- Hand completed machine jobs back to their owners through the scoped handover workflow.

**Honest limits:** without the Machine service module, machines are records rather than a job queue. The
system records machine work but does not read live state from printers, CNC controllers or other hardware.

## 3D printing and filament

- Accept public print requests and files.
- Manage printers and spools, track filament use and store slicer estimates.
- Present print-specific intake and queue views on top of the general machine service workflow.
- Support an optional staff-private cash charge at collection.
- Use the broader Payments module when online checkout, receipts and reconciliation are required.

**Honest limits:** Printing depends on Machine service. Without the Printing module, a 3D printer can still
be registered and its work can use the generic service queue, but the print-specific intake and handling
disappear.

## Events and bookings

- Publish events, accept member registrations and let staff register a person from the console.
- Check attendees in by QR code and retain attended-event history on opted-in maker profiles.
- Run collaborative events across makerspaces with collaborator records and host-waiver acceptance.
- Define bookable resources and rules, manage reservations, and offer public self-booking.
- Include bookings in member activity history.
- Optionally charge for event registrations and bookings through the same payment system used by other parts of the platform.

**Honest limits:** Events and Bookings are separate optional modules. Removing either removes its public
listing and staff workflow, and makes its matching payment switch inert.

## Payments

- Take online payments through Stripe or Razorpay behind a common payment workflow.
- Create charges and receipts for machine jobs, bookings, events and membership dues.
- Settle checkout and webhook updates, reconcile payments, and keep payment records attached to a stable
  description even if the originating optional module is later removed.
- Support managed Stripe Connect resolution and an in-app PaymentSheet when the mobile substrate is also
  enabled.
- Enable payments globally and then independently for machines, bookings, events and membership.

**Honest limits:** installing Payments does not begin charging. The master switch, the relevant area switch
and valid provider credentials must all be present. Payment records are deliberately not erased by a
module-data purge because they record real money movements.

## Notifications and integrations

- Provide an in-app inbox with read/unread state.
- Send makerspace mail through that space's SMTP configuration; account recovery and verification use platform mail so disabling tenant email cannot lock users out.
- Send alerts to Telegram, Slack, Mattermost and Discord. Each outbound channel is an independent module.
- Review hardware requests in the staff console or `/control/`; Telegram alerts carry no decision buttons.
- Create multiple chat rooms and narrow each one by machine, machine type or inventory category.
- Choose notification recipients by role, named member, all members or the person the event concerns,
  while still respecting that person's permissions and notification preferences.
- Edit email templates for hardware, printing, events, bookings, maintenance and membership; edit one chat
  message body shared across all four chat channels.
- Register and revoke attested device sessions and send native push when a compatible app is connected.
- Encrypt per-makerspace Telegram and SMTP secrets at rest, expose them as write-only settings, and keep
  one makerspace's integrations isolated from another's.

**Honest limits:** enabling a channel does not configure it. Email needs SMTP credentials; Telegram needs a
bot and chat; Slack, Mattermost and Discord need webhooks; push needs FCM or APNs. Native push and device-session
support ship on the server, but a first-party native app does not.

## Reporting and analytics

- Show operational dashboards and an inventory ledger.
- Report what is issued, who holds it, overdue items and problem records.
- Use a central report registry so inventory, machine and event reporting can share one export surface.
- Export registered reports as CSV or XLSX.
- Keep Reports independent from Inventory so machine and event reports do not vanish because an inventory
  option changed.

**Honest limits:** without the Reports module, the console has no analytics screens or report exports; the
underlying operational records remain owned by their original modules.

## Multiple makerspaces and organization accounts

- Host many makerspaces on one deployment. Each tenant owns its inventory, public URL, staff memberships, custom roles, integrations, QR namespace and audit scope.
- Keep public and staff queries scoped to the selected makerspace.
- Move stock through an explicit cross-makerspace transfer rather than silently changing another tenant's
  count.
- Represent a network, university or chain as an organization linked to several makerspaces as owner,
  manager or affiliate.
- Give organization staff selected actions across linked spaces without creating a separate login and
  duplicate membership in every space.
- Keep organization authority separate from identity and expose cross-organization reach in a dedicated,
  read-only view rather than mixing it into the local staff roster.

**Honest limits:** integrations are stored per makerspace; there is no shared SMTP or Telegram credential
object for an organization. Spaces that share a service enter the same credential independently.

## API access for integrators

- Expose documented REST APIs with OpenAPI schema, Swagger UI and ReDoc.
- Issue API clients with encrypted HMAC secrets and versioned scopes.
- Maintain a registry mapping each scope to the protected routes it may call, with deployment checks that reject newly protected routes that were not classified.
- Support API-key access requests and staff-controlled client issuance.
- Keep browser and API access tenant-scoped rather than trusting a client-supplied makerspace alone.

**Honest limits:** API access is not a universal master key. Clients must sign requests and hold a scope
registered for the exact protected route.

## Backup, export and data ownership

- Back up and restore a whole deployment, including recovery controls that quarantine normal application
  traffic while restoration is in progress.
- Let a Space Manager export tenant data in redacted or portable forms.
- Move one makerspace from a hosted deployment to its own server as an `age`-encrypted archive containing its rows, approved personal data and uploaded files.
- Require explicit approval of the people whose contact details will travel in a tenant migration; carry
  unapproved people as opaque references.
- Freeze source writes for the final snapshot and keep the destination closed until rows and files verify,
  so both deployments are not writable during cutover.
- Archive the source tenant after migration rather than silently deleting the accountability record.
- Keep module uninstall reversible by retaining its rows; make destructive module-data purge a separate,
  confirmed, superadmin-only operation.

**Honest limits:** an archived source tenant is outside the normal purge guarantee. A failed object deletion
does not release its storage quota, and financial records survive module purges. Those choices favour an
accurate record over a cosmetically empty database.

## Security and privacy

- Isolate each makerspace's records and scope staff permissions to both tenant and action.
- Keep evidence in private object storage and serve it only through short-lived signed URLs to active,
  authorized staff.
- Keep integration secrets encrypted at rest and write-only in staff-facing APIs.
- Make evidence and QR scan records immutable and the audit log append-only, including database-level
  protection for audit rows.
- Rate-limit login and public request submission, lock out repeated admin-login failures, and use a hidden honeypot field against automated public submissions.
- Apply production security headers and an always-on Content Security Policy; run dependency auditing in
  continuous integration.
- Restrict the superadmin control plane to superadmins and keep it off the public frontend port.
- Allowlist public inventory fields so storage locations, box IDs, QR data, scan history, evidence,
  requester history and hidden counts never appear in public responses.
- Force the generated first administrator to change the setup password on first login.

**Honest limits:** TLS is supported but disabled by default in the installer and must be enabled for a
production deployment. Self-hosters remain responsible for host security, backups, provider credentials
and operational monitoring.

## Modules and positioning

The [landing-page modules and positioning](LANDING-PAGE-POSITIONING.md) companion contains
the optional-module comparison, feature switches, audiences, deployment options, differentiators
and features that have not shipped.
