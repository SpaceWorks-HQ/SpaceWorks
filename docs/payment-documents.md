# Receipt documents and finance exports

Receipts and credit notes belong to the permanently core payment ledger. They work
without an installed online rail. `billing.documents` is a standalone feature, enabled
by default. Turning it off prevents documents for newly collected charges; existing
documents remain readable, and refunds/corrections on a documented charge still append
the documents needed to explain its history.

One gapless sequence is shared by receipts and credit notes within a makerspace.
The billing-settings counter and document INSERT commit with settlement; rolling back
settlement rolls back the number. A locked makerspace row serializes first-use policy
creation, then a locked policy row allocates the number. Prefix changes affect future
numbers only. The counter cannot be edited through the API.

Each document snapshots the issuer, payer username label (no email/phone), one implicit
charge line, gross amount, currency, method/reference and money timestamp. The existing
ledger has one amount per charge; this does not introduce PaymentLine or instalments.
Rows reject model updates/deletes and SQL updates/deletes, except deletion within the
existing whole-tenant purge transaction. Corrections append an offsetting document and
a replacement; a refund only receives a credit note once it succeeds.

These are informal gross-only payment acknowledgements. The nullable `tax_breakdown`
is reserved, constrained to NULL and unused. An issuer identifier is presentation
metadata, not a tax rate or a claim of jurisdiction-specific legal compliance. Tax
handling (owner decision O3) remains outside this lane.

The payer's own account email receives a link to the authenticated member page after
commit, through the existing mail dispatcher and email module gate. No caller chooses
the recipient. SMTP failure cannot undo collection; it logs the document identifier
without recipient or secret data. Mail uses a durable member-page link instead of a
grant that could expire while waiting in an inbox. PDF downloads are rendered server-side
with the already-installed ReportLab dependency. No stored PDF object or heavy dependency
is added. A five-minute signed URL is bound to the requesting user and member/staff
scope; download requires authentication and rechecks current authority. Staff downloads
also recheck active/unrestricted status, required password rotation and browser origin
scoping, even when the URL was issued before those conditions changed. VIEW_FINANCE
staff see the tenant ledger; members see only documents on their own visible payments,
including collaborative-event routing and archived-space recovery.

The report registry adds:

- `payments-ledger`: charges, online/manual settlements, waivers and all refund attempts
  lines. Correction history remains visible; only effective heads carry money columns.
  Payer identity is an account ID/type, without contact details or a personal label.
- `revenue-over-time`: collected, currently owed, refunded, waived and net amounts by
  local day, Monday-start week or month, subject type and currency. Owed is current
  pending debt allocated to its creation period, **not** a historic outstanding balance.
- `cash-book`: effective offline money in/out, by local period, method and currency.
- `accounting-journal`: balanced cash-basis generic CSV journal from issued documents,
  with date, document number and configurable accounts. It does not claim a vendor's
  import format. Defaults: income 4000, cash 1000, online 1010, deposit liability 2100;
  subject-type mappings override income/deposit. It excludes undocumented historical
  settlements and charges collected while issuance was disabled.

Money dates use effective ManualSettlement.received_at / Refund.refunded_at for offline
money and the online settlement's Payment.updated_at snapshotted at issue. Online
refunds use Refund.settled_at. Historical undocumented settlements explicitly fall back
to Payment.updated_at and unknown offline method. API calendar filters are converted
to the makerspace timezone, including DST; rolling schedules retain precise instants,
including UTC-midnight bounds. Calendar ranges carry an explicit type marker rather
than inferring their meaning from the timestamp's hour.
Currencies are never combined. All four reports require VIEW_FINANCE and the reports
module; disabling reports returns 400. They inherit provenance and CSV formula escaping.
The ledger/accounting detail reports stay out of deployment aggregates. Organization
combined reports exclude all four: mixing different local calendars would be misleading.

Portable dumps include documents, numbering state and billing presentation/mappings.
Document/refund/settlement/reversal and issued-by references remap normally. No PDF
storage keys or source download grants travel. The money fingerprint includes appended
documents and numbering settings (even before the first receipt), so issuing/correcting
a receipt or changing numbering after capture requires a
fresh capture before publication. The coordinator must recompute the integration
catalog digest and regenerate the OpenAPI snapshot/client after merging lanes.
