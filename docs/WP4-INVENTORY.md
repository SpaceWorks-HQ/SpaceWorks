# Inventory and machine operations (WP4)

All seven new feature keys are opt-in. They use the existing module registry;
no new module is installed and no existing request status changes.

| Feature | Behaviour |
| --- | --- |
| `inventory.notify_when_back` | Active members subscribe their own account to a public product. The availability service latches the first positive stock rise in its transaction; F1 consumes one occurrence. Delivery uses the hardware notification family with staff channels disabled, current member eligibility and personal preferences. A notification never includes stock counts. |
| `stocktake.discipline` | A space manager configures blind defaults and an absolute variance threshold per line. Null keeps mandatory approval; a configured threshold permits automatic approval within the limit. A count above the threshold requires a different manager to approve. Sessions snapshot the policy. Scheduled sessions are system-created through F1 without impersonating a device or user. Missed intervals produce one session. |
| `machines.public_detail` | The new `machines/views_public_detail.py` serves public details and a paginated collection. Status-since is maintained by a database trigger. Per-machine `public_fields` can opt into training and aggregate queue estimates; both default hidden. Unknown run estimates produce an unknown ETA. Camera URLs, locations, job descriptions and requester identities are excluded. |
| `maintenance.meters` | Schedules use days, usage, or either trigger. Hours and jobs are derived from independent usage entries plus terminal service runs; linked usage entries are excluded to avoid counting a run twice. Completion resets the baseline at server completion time and keeps existing recurrence anchors. Calendar and meter reminders use separate occurrences. |
| `machines.material_catalogue` | The migration seeds existing spaces from the global printer pack. An unconfigured space falls back to that pack. Local rows override it per type, including an explicitly empty active catalogue. Material/colour pairs are validated together. Local materials never edit the global pack or introduce pricing. |
| `machines.structured_intake` | A space manager configures version-1 custom-type fields. Text, numeric, integer, choice and boolean values are validated before submission. Unknown fields, reference-ID field names, stale versions and out-of-range values are refused. Built-in printer intake stays protected. |
| `maintenance.calendar_feed` | A staff user issues or rotates a personal hashed bearer feed. Every read resolves that user's live machine scope. Rotation/revocation invalidates old tokens. Only dated active schedules become all-day events; usage-only thresholds do not invent a date. Token paths are redacted from Django/Gunicorn request-line sources, and both shipped nginx configurations suppress access/error logging for bearer feed paths. |

Borrowing terms are always part of the public product allowlist. The badge derives
loan days and an applicable deposit from existing policies and appends the item's
optional public text. Staff can edit that text in the inventory form.

Portable exports retain materials, intake schemas and counting preferences. Target
projection resets optional public machine disclosures, variance auto-approval and
scheduled-count activation. Personal stock watches and feed credentials are omitted.
Module purges remove stocktake policies/schedules and maintenance feed credentials.
Deletion audit targets for material/count schedules remain inert source provenance.

New backend tests cover these contracts in `tests/test_inventory_notify_me.py`,
`tests/operations/test_stocktake_discipline.py`,
`tests/machines/test_public_machine_detail.py`,
`tests/machines/test_material_catalogue.py`,
`tests/maintenance/test_meter_schedules.py`,
`tests/maintenance/test_maintenance_feed.py`, and `tests/test_wp4_contracts.py`.
The public-inventory regression collection was split behind explicit imports and
its field allowlist includes borrowing terms.

Coordinator checks: run the isolated database tests, migration drift check,
OpenAPI generation and merged tenant-catalog digest repin. This lane does not
regenerate either frontend generated API artifact.
