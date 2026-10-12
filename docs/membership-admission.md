# Membership admission

Admission settings belong to the existing optional `membership` module. A Space
Manager configures them; a role with `manage_members` reviews community applications.
Configuring admission never grants staff actions to an applicant.

## Upgrade compatibility

Every makerspace receives a settings row with `configured=false`. Until its manager
saves admission settings, the existing open/request/invite policy, referral behaviour,
activate-then-charge and once-per-membership joining dues remain authoritative.
Existing submitted applications retain their submission behaviour. Community
invitations in a configured space must be claimed before approval, so their answers
and payment conditions cannot be bypassed. Staff invitations retain their core RBAC
path when membership is off. Closed admission, when the module is on, refuses new
joins, invitations, referrals, anonymous invitation leads and walk-in admissions.

The existing makerspace PATCH fields remain writable aliases: `request` maps to
`approval`, and `membership_dues_amount` maps to the joining fee. The new editor can
express vouching and closed admission, which the legacy policy field cannot represent.

## Conditions and recipes

Open admission activates after its configured form and payment conditions. Approval
requires a membership reviewer. Invite-only requires a matching authenticated claim
and reviewer approval. Vouching requires eligible vouches and reviewer approval unless
`vouch_replaces_approval` is enabled. Closed refuses every new join path with the
typed `membership_closed` error.

Recipes prefill editable settings. Paid recipes choose payment before activation;
their actual plan/fee must be selected by the manager. No price is invented. Free
recipes clear retained pricing. Managers can combine any mode with free or paid
plans and either payment timing.

Vouch defaults are one vouch, 30 days' active tenure and at most three pending
applicants per voucher. Both application and vouch expiry default to 30 days.
Restricted, suspended, inactive or revoked accounts cannot vouch. Eligibility is
rechecked before approval and settlement-driven activation. A different eligible
member can supply a replacement if an earlier voucher becomes ineligible while
payment is pending. Vouches remain immutable evidence; revocation flags the vouchers
in the audit trail without restricting them. Reviewers see named vouchers on the
application and member record. The voucher endpoint returns only request ID/state.
Reviewers need `view_finance` to see admission charge summaries. Membership review
authority alone still exposes the application and vouches, while applicants retain
access to their own charge. Staff invitation claims bypass community questionnaires.

Application questions reuse the shared custom-form validation and answer snapshot.
Answers are encrypted PII, remain tied to the submitted question labels, and appear
only in the review queue and the applicant's own admission/export surfaces.

## Payments and activation

Approval snapshots the selected plan's first-term amount and the joining fee into
one request-owned charge. A joining fee applies once by default, or on each rejoin
when configured. Each admission's first plan term is still charged. Both amounts
must use the same currency. Free admission works without charge tracking; paid
before-activation admission requires tracking, which is independent of the online
payment rail.

`awaiting_payment` is a request state. It never creates a new membership status or
grants access. A payment settled online, offline with a `ManualSettlement` receipt,
or waived schedules activation after the settlement transaction commits. The
activation service rechecks module, tenant, applicant, expiry and vouch conditions
under the tenant write gate and makerspace/request locks. A failed callback leaves the payment recorded
and the application pending for a scheduler retry.

Activate-then-charge grants membership and creates its first term in one transaction.
Unpaid cancellation/expiry closes the request and cancels its pending charge. A late
settlement remains in the ledger and never grants expired admission. A settled charge
is never erased by cancellation. Deactivating a selected plan blocks activation until
the plan is available again; collected money remains recorded.
Revoking an admitted member cancels any unpaid activate-then-charge admission debt
and preserves every settled charge and manual receipt.

Returning revoked members may access only their new approved, unexpired admission
charge. This does not expose previous revoked-member debt or confer community access.
Native payment intents retain the existing active membership/device-grant requirement;
an applicant uses hosted checkout or a recorded offline settlement.

Staff can collect a walk-in's application answers. Pending walk-ins appear in the
review/payment queue and are never automatically selected as hardware borrowers.
Only a membership manager can satisfy an approval or invite-only decision gate.

## Notifications, scheduler and portability

Application receipt uses the F3 MEMBERSHIP staff family. Decisions, awaiting-payment
and payment-due notices resolve the applicant's owned account address, respecting
existing delivery gates and preferences. F1 schedules one deduplicated reminder one
day before expiry. Admission expiry and settlement retries run every five minutes in
Celery beat and the beatless scheduler. Turning membership off suspends these flows.

Export/PII/user-reference, purge and tenant-migration registries include both new
models and request fields. Portable dumps retain debt and voucher evidence, clear
source approval/activation authority and project pending managed requests to inert
canceled history. The target cannot activate a source application by settling its
imported charge. Membership purge removes admission data in FK-safe order and retains
the permanently core payment ledger.
The applicant export takes an explicit tenant write boundary because its GET route
records an audit row. A frozen source refuses it with a typed 423 response.

## Coordinator verification

Run the isolated database tests listed in `LANE-PROGRESS.md`, migration drift checks,
OpenAPI generation and browser QA before integrating. The sandbox has no Django,
Docker or Postgres access; database tests and migration execution were not performed.
Frontend focused tests and TypeScript checking were run. No generated OpenAPI/client
files were edited by this lane.
