# Module reference

[Module guide and feature switches](MODULES.md)

## Inventory

The permanent heading. It absorbs all six core keys, so this area has no master switch — but nine of the
thirteen modules under it are optional.

### public_inventory

**Core — cannot be uninstalled.**

- **What it is** — the public browse catalogue and item detail pages at `/m/<slug>`.
- **What it adds** — the `catalog` workflow: the public product list and detail view.
- **Without it** — not an option. It is the surface the whole system exists to publish. What you *can*
  control is per item: `is_public` removes a product from the public list entirely, and
  `public_availability_mode` (`exact_count` / `status_only` / `hidden`) decides how much of its stock
  level a visitor sees. A space that wants no public catalogue publishes nothing.
- **Data** — core; not separately purgeable.

### request_workflow

**Core — cannot be uninstalled.**

- **What it is** — member hardware requests and the state machine behind them
  (`draft → pending_approval → accepted → issued → returned`).
- **What it adds** — the `request_submit` and `request_status` workflows: submitting a borrow request
  and following it, plus the staff review queue.
- **Without it** — not an option. Every handover in the system — staff issue, front-desk handout, member
  self-checkout — records itself through this workflow, and it is the only place a request's status is
  allowed to change.
- **Who may submit is set by `membership`, not by this module.** Being core, this module is present in every
  makerspace and therefore must work with `membership` uninstalled: members only when `membership` is on,
  any signed-in account when it is off, and account-less strangers only when an operator has explicitly
  opted in (`manage.py set_request_access --mode anyone`, which is refused while `membership` is installed).
  See the `membership` module below, and **Who may submit a borrow request** in `docs/INVARIANTS.md`.
- **Accept and reject are one request at a time.** There is no bulk accept or bulk reject anywhere —
  `/control/` serves a per-request review page, and Telegram alerts carry no buttons.
- **Data** — core; not separately purgeable.

### staff_admin

**Core — cannot be uninstalled.**

- **What it is** — the staff console's inventory and request administration API.
- **What it adds** — the `staff_inventory` and `staff_requests` workflows: products, categories, assets,
  the needs-fixing queue, exports and the request review screens; plus the **audit explorer** (the
  `VIEW_AUDIT`-scoped audit list with safely projected metadata, the request timeline's audit rows and
  evidence-retention state, and asynchronous integrity verification runs). The `audit-trail` CSV export
  additionally needs the `reports` module.
- **Without it** — not an option; a space with no staff console cannot be run. Who sees what inside it is
  a **roles** question, not a module one — see the role/action matrix.
- **Data** — core; not separately purgeable.

### evidence_uploads

**Core — cannot be uninstalled.**

- **What it is** — immutable issue and return evidence photos (once attached) in a private bucket.
- **What it adds** — the `evidence_uploads` workflow: presigned upload, and the photo attached to every
  issue and return.
- **Without it** — not an option: hardware cannot be issued without an issue photo, nor returned without
  a return photo and a remark. That is the accountability rule the product is built around.
- **Data** — core; not separately purgeable. Attached evidence rows are immutable and only ever removed when the
  whole makerspace is purged. The *object bytes* are a separate question: an optional per-makerspace
  retention policy deletes the stored image once its window passes, keeping the immutable row, the
  remarks, the QR scans and the audit trail. An expired photo then reads as a truthful expired state
  (410) rather than a broken link, so the accountability record survives the picture.
  Separately, a default-off abandoned-upload cleanup (deployment switch plus per-space opt-in) may
  delete an old upload slot that no workflow ever consumed; it never touches attached evidence or rows
  recorded before the feature, and it leaves a permanent receipt that keeps re-deleting a late upload.

### qr_management

**Core — cannot be uninstalled.**

- **What it is** — generating, revoking and printing the QR codes for boxes, tools and asset units.
- **What it adds** — the `qr_generate`, `qr_revoke` and `qr_print` workflows, plus QR rebinding.
- **Without it** — not an option: issuing reviewed-request hardware requires a box QR scan, so a space
  with no QR codes could not complete a handover.
- **Data** — core; not separately purgeable. Scan records are immutable.

### scanner

**Core — cannot be uninstalled.**

- **What it is** — the camera scanner and the container lookup it feeds.
- **What it adds** — the `qr_scan` and `container_lookup` workflows.
- **Without it** — not an option, for the same reason as `qr_management`: no scan, no handover.
- **Data** — core; not separately purgeable.

### asset_units

- **What it is** — individually QR-tracked units of a product, so "drill #3" is a thing rather than "one
  of four drills".
- **What it adds** — per-unit QR generation and asset-level status tracking; asset units become
  selectable at issue time.
- **Without it** — products are tracked by **quantity only**. Availability maths, requests and handovers
  all still work; you simply cannot say *which* physical unit went out, and per-unit QR labels are
  unavailable.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately.

### containers

- **What it is** — the physical container hierarchy (boxes inside shelves inside rooms) and moves
  between them.
- **What it adds** — creating and listing containers, the parent/child hierarchy and container moves; a
  direct handout can resolve a scanned container into the loan.
- **Without it** — you cannot create, list or re-parent containers in the console, and a direct handout
  will not accept one. Storage location stops being modelled as a hierarchy. Scanning a box QR still
  resolves — that is [`scanner`](#scanner) — and containers that already exist keep their codes, so the
  box-scan-at-issue rule is unaffected.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately.

### bulk_import

- **What it is** — spreadsheet import of inventory rows.
- **What it adds** — the `bulk_import` workflow: upload a sheet, map columns, preview, commit.
- **Without it** — inventory is created one product at a time in the console (or through the API). The
  most common reason to install it is the first week of migrating from a spreadsheet.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately.

### stock_transfers

- **What it is** — moving stock between locations, including true movement **between makerspaces**.
- **What it adds** — the `stock_transfer` workflow: raise a transfer, its lines, and the receiving side.
- **Without it** — stock stays where it was booked in. A multi-space operator loses the only supported
  way to move quantity across a tenant boundary without editing counts by hand.
- **Data** — purgeable: transfers and their lines.

### qr_print_batches

- **What it is** — batched QR label generation as a downloadable ZIP.
- **What it adds** — the `qr_print_batch` workflow: select items or asset units, generate a sheet, keep
  the batch as a record.
- **Without it** — QR codes still exist and still print one at a time from `qr_management`; what you
  lose is generating and re-downloading a whole sheet at once.
- **Data** — purgeable: print batches and their items.

### guest_handover

- **What it is** — the narrow front-desk console: hand out an accepted request, take it back, without
  seeing the rest of the admin.
- **What it adds** — the `guest_issue` and `guest_return` workflows, and direct handouts at the counter.
- **Without it** — handovers happen in the full staff console instead. Front-desk volunteers then need a
  role with wider access than they should have, which is the reason this module exists. The handover
  **role** is a separate concept: a custom role holding the handout actions, editable per space.
- **Data** — `purge_module_data` reports it stores no data of its own to purge separately; the requests
  and evidence it produced belong to the core loan spine.

### procurement

- **What it is** — the "to buy" list and the receipts attached to it.
- **What it adds** — the `procurement` workflow: raise a to-buy item, track it, attach a receipt, and
  move a purchased item into stock.
- **Without it** — restocking is tracked outside the system. Low-stock signals still show in inventory;
  there is just nowhere in-app to record what was ordered.
- **Data** — purgeable: to-buy items and their receipts (including the uploaded receipt files).

---

## Stocktake

### stocktake

- **What it is** — scan-first stock counts and the variance they produce.
- **What it adds** — the `stocktake` workflow: open a session, scan through the shelves, review variance,
  commit the adjustment as a ledger entry.
- **Without it** — counts are corrected by editing quantities directly, with no session, no variance
  report and no audit of the count as an event.
- **Data** — purgeable: stocktake sessions, lines and ledger entries.

---

