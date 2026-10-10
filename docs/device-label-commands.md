# Label commands (forward phase 7c)

An operator with `MANAGE_QR` can send an existing nonempty QR print batch to an
enrolled, active label printer in the same makerspace. Both `devices` and
`qr_print_batches` must be enabled. Enrollment/key administration still requires
`MANAGE_DEVICES`; sending labels does not grant it. No new module or feature key
is introduced.

`POST /api/v1/admin/qr-print-batches/{batch_id}/label-commands` accepts
`device_id` and a caller-generated `request_id` UUID. An identical request returns
the original command; conflicting reuse returns 409. GET lists paginated history.
A first send marks DRAFT as PRINTED in the same transaction as command creation.
PRINTED batches can be reprinted with a new request UUID; ARCHIVED and empty batches
are refused. Adding or relabeling items locks the batch and accepts DRAFT only,
including when a caller supplies an old in-memory batch instance.
The `/control/` editor also locks saves against first-send, exposes status only as
read-only, and refuses parent/inline edits on PRINTED or ARCHIVED batches.
Asset generation takes the makerspace lock before product and batch locks, keeping
the same order as sending and managed quota checks and preventing a quota deadlock.

The shared 7b lease/ack protocol delivers `kind=label_print`, `label_command_id`,
`qr_batch_id` and `item_count`. Only the assigned current signed device can download
`GET /api/v1/device/label-commands/{label_command_id}/content` after acknowledging.
The short lease governs acknowledgement; it does not interrupt an acknowledged long
print. Downloads stream the existing authenticated in-memory ZIP of SVG labels,
with a UUID-based safe filename and `Cache-Control: no-store`. ZIP entry timestamps
may differ across downloads; the frozen label contents remain the same.

`POST /api/v1/device/label-commands/{label_command_id}/result` accepts `operation_id`,
`outcome` (`succeeded`, `retryable_failed`, `failed`) and an allowlisted `result_code`.
Supported codes are `ok`, `out_of_labels`, `paper_empty`, `offline`, `printer_error`,
and `unknown_error`. `ok` is required for success and forbidden for failures.
Unknown fields and arbitrary printer messages are rejected. Fixed server messages
provide usable status without retaining device-supplied secrets or PII.

Each operation writes an immutable `LabelPrintResult` receipt and updates delivery
state atomically. A matching replay returns the same response snapshot even after a
later retry succeeded; conflicting reuse is 409. Retryable failures reuse 7b's bounded
exponential backoff and attempt limit. Permanent/exhausted failures are terminal.
This is at-least-once delivery: the physical printer must honor command identity;
an HTTP timeout alone cannot establish whether it printed a label.

Device actions use `AuditLog.actor=None`, typed remappable IDs and an append-only
DeviceEvent; staff sends use the real User. Neither QR payloads nor ZIP bytes enter
audit metadata. Source gates and current key/status/module checks apply at the locked
service boundary. Disabling the adapter or purging its batch cancels queued delivery;
historical snapshots cannot be used to render or recreate a purged batch.

The label command's batch FK is nullable SET_NULL, allowing independent
`qr_print_batches` purge. Devices purge deletes immutable receipts and label parents
before command/device rows. Portable movement exports print history, remaps live FKs
and typed audit references, and preserves source-local snapshots. Imported commands
are permanently cancelled with lease and acknowledgement ownership cleared. Receipts
remain history and never replay printing. Full deployment backup preserves raw rows;
the existing device recovery quarantine invalidates keys, so restored hardware cannot
use its old command authority.

No PDF, rasterization, artifact field, stored ZIP, object key, presigned URL, storage
quota entry, agent, printer protocol integration or staff UI is added. The archive,
object ownership, storage accounting and encryption registries were reviewed and need
no label entry because there are no persisted bytes, credentials or new PII fields.

Implementation lives in `devices/models_labels.py`, the `services_label_*` modules,
`label_access.py`, `serializers_labels.py`, `views_labels.py`, and dedicated `*_7c`
catalog siblings. `operations/services_qr_assets.py` owns the common batch freeze;
`operations/qr_zip.py` remains the canonical renderer. QR admin registration is
split into `operations/admin_qr_batches.py` and explicitly re-exported by `admin.py`.
