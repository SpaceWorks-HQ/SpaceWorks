# Printing kernel cutover (B4) — COMPLETE, historical

> **This is a record, not a runbook. The cutover is finished and its tooling is deliberately gone.**
> Nothing here is runnable. It is kept to explain why `PrintingCutoverRepair` rows and the kernel
> provenance fields exist, and to preserve the rollback-boundary reasoning, because both outlive the
> migration that produced them.
>
> - `cutover_printing_kernel --makerspace <id>` was the forward-only import gate. **`237e0f36` (B7c)
>   deleted it**, along with the whole `apps/printing` runtime, replacing it with a read-only
>   `verify_printing_retirement_ready` command plus a legacy write-fence.
> - **`911f4589` (B7d) then deleted that successor too**, when it retired the legacy printing tables
>   through a tombstone migration.
>
> So neither command exists. If you came here looking for one, you want the machines kernel
> (`apps/machines/`) — see `docs/SOURCE-MAP.md`. Both retired implementations remain recoverable from
> git history at `237e0f36^` and `911f4589^`.

## What the cutover did

`cutover_printing_kernel` was a deterministic, idempotent backfill and reconciliation gate. It wrote
kernel provenance keys only; it never altered legacy printing history. Invalid sources, missing
objects, collisions, warranty problems and reconciliation mismatches were each recorded as an
explicit `PrintingCutoverRepair` row rather than being silently fixed or skipped.

Its three stages were: run the backfill, run `--reconcile-only` after any repair, then `--flip` once
reconciliation was clean. The flip marked a makerspace kernel-authoritative and made the legacy
printing models read-only, keeping the old endpoints as compatibility readers through B6.

## What still exists today

- **`machines.PrintingCutoverRepair`** — the forward-repair queue, surfaced through a **read-only**
  admin (`PrintingCutoverRepairAdmin`). Existing rows are an audit artifact of the migration; imported
  history is never edited.
- **`apps/machines/printing_cutover_models.py`** and migration
  `machines/0013_printing_kernel_cutover_provenance` — the provenance fields the cutover wrote.
- The legacy printing tables are **tombstoned** (B7d), not dropped.

## The rollback boundary — why forward repair was the only option

This is the part worth keeping, because the same rule governs every append-only surface in the
system. Rollback was safe only *before* `--flip`. Once a kernel write, a consumable-ledger adjustment
or an attachment had been accepted, copying it back would have broken the append-only ledger and
audit trail and corrupted storage accounting.

So the repair path was always forward: add the missing kernel record or ledger correction, retain the
repair row and its audit link, rerun the idempotent command, and reconcile that makerspace again.
Legacy writes were never restored and imported immutable history was never edited. A missing storage
object stayed an explicit repair record — no replacement attachment was ever fabricated.
