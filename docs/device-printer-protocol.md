# Printer delivery and measured terminal reports

Phase 7b uses the [device signature protocol](device-protocol.md). A Device holds no staff role.
Every device request uses a fresh signed nonce, including retries of an identical report. The stable
terminal operation UUID is a separate identity used to prevent duplicate workflow effects.

Staff hold `MANAGE_DEVICES` and current management scope for the selected Machine. The adapter
requires all three modules: `devices`, `machines`, `machine_service`. Disabled modules answer 400;
a tombstoned devices app has no routes and answers 404.

## Bind and create

`POST /api/v1/admin/makerspace/{makerspace_id}/device-printer-bindings`:

```json
{"device_id":"<enrolled-printer-uuid>","machine_id":123,"enabled":true,"auto_apply_terminal":false}
```

The device and machine must be active and belong to that makerspace. Binding policy is updated with
`PATCH /api/v1/admin/device-printer-bindings/{id}` (only `enabled` and `auto_apply_terminal`). DELETE
removes the binding. Disabling or deleting it cancels unprocessed commands and preserves job history.

`POST /api/v1/admin/makerspace/{makerspace_id}/printer-jobs`:

```json
{"binding_id":"<binding-uuid>","service_request_id":456,"external_job_id":"agent-job-123"}
```

The request must already be in progress and assigned to the exact bound machine. External identity
is immutable, unique per device, and never inferred from a filename or request title.

Both staff collections support paginated GET. Job detail is
`GET /api/v1/admin/printer-jobs/{id}`. Swagger documents request, response and refusal schemas.

## Delivery ownership

`POST /api/v1/device/commands/lease` with `{}` returns `{"command":null}` or a command containing
`command_id`, `kind`, `lease_token`, `lease_expires_at`, `printer_job_id`, `external_job_id` and
`service_request_id`. Only the exact active owning device can receive it. The token is returned once;
its SHA-256 digest is stored, omitted from exports and never returned to staff.

`POST /api/v1/device/commands/{command_id}/ack` with `{"lease_token":"<returned-token>"}` acknowledges
ownership. Identical acknowledgement is cached success. A wrong or replaced token conflicts with 409;
expired unacknowledged delivery answers 410 after committing requeue/backoff. Delivery leases default
to 60 seconds and at most 10 attempts. Expiry is processed lazily when polling/acknowledging.

Acknowledgement survives a long print. Later telemetry/results require the owning device signature
and acknowledged command; they do not need an unexpired delivery lease. Rotation or revocation
invalidates prior command ownership. Agents must keep a durable local mapping from the server job ID
to their actual print; transport delivery may happen more than once.

## Telemetry and terminal result

`POST /api/v1/device/printer-jobs/{id}/telemetry`:

```json
{"external_job_id":"agent-job-123","telemetry_state":"running","progress_percent":25}
```

State is `idle`, `running` or `paused`. This only updates advisory job fields and device last-seen.
It does not change `Machine.status`, the public response, consumption or money.

`POST /api/v1/device/printer-jobs/{id}/result` for completion:

```json
{
  "operation_id":"<stable-operation-uuid>",
  "external_job_id":"agent-job-123",
  "outcome":"completed",
  "actual_minutes":42,
  "consumptions":[{"machine_consumable_id":789,"quantity":"2.50"}],
  "actual_grams":"12.00"
}
```

`consumptions` is required, including an explicit empty list. These are existing `MachineConsumable`
inputs belonging to the assigned machine. Count inputs must be whole. `actual_grams` is only for an
existing reserved weight pool. A non-weight reservation instead requires `actual_quantity`, matching
its unit. Omit both when no pool is reserved; never send both. All measurements must be finite and
nonnegative (individual consumption quantities must be positive).

Failure uses `outcome:"failed"` and additionally requires nonblank `failure_reason` (maximum 1000
characters) and `percent_complete` (0–100). It accepts the same metering inputs and creates no payment.
Completion cannot include failure fields. Unknown fields, including price/amount/currency/payment
status, are refused. Charges are calculated by the existing workflow using current tenant pricing.

The server commits the immutable report before attempting workflow effects. Retrying the same
operation and canonical payload returns the stored job; changing either conflicts with 409. Keep the
operation UUID stable across transport retries, and use a fresh signature nonce each time.

Automatic application is opt-in per binding. By default a report becomes `needs_review` and leaves the
request running. Scoped staff apply it with
`POST /api/v1/admin/printer-jobs/{id}/apply` and `{}`. Application and its provenance commit together.
A workflow or applied-provenance failure rolls back all effects and records review in a new transaction;
review is never retried automatically. Admission failures remain typed refusals.

## Movement and retention

Tenant moves preserve typed reports and source snapshots, disable bindings, cancel commands, remove
lease authority and reset devices to pending. Applied history stays applied; unprocessed work becomes
inert review. Re-enrollment does not revive imported work. Device purge removes the printer ledger;
machine-adapter purge nulls live targets while retaining device history. Missing targets cannot deliver
or apply. Free-text printer failure notes use scoped encryption; adapter audit metadata contains only
typed identifiers and outcomes. The existing workflow's reason fields retain their existing storage
contract.
