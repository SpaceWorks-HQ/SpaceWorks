# Stage 1 — phase 7b review against lane/7a

Reviewed phase-7b-printer-jobs.md, phase-7-hardware-integration.md, reviews/stage1-p7.md and HANDOVER-CODEX.md section 7 against this tree. This lane-local audit must be copied by the coordinator to docs/plans/2026-09-03-forward-plan/reviews/stage1-p7b.md in the main checkout; writing there is outside the explicitly authorized lane boundary.

## Stale facts corrected

- Registry split already exists: module_registry_catalog.py, classification_domain.py/classification_platform.py, references_core.py and unique_values_core.py. Use new *_7b siblings and thin union hooks, not grow or split the old barrels again.
- Actual leaves: devices/0001_device_identity.py, machines/0024_certifications.py and encryption/0007_tenant_import_fence_operation.py. The printer PII trigger adds the encryption leaf to the two correct plan dependencies. Printing/0022 is retired and is not a workflow target.
- 7a already provides makerspace-first source-gated locks, signed principal/authentication, route checks, immutable event snapshots, inert import and restore quarantine. Reuse these; the proposed job-first lock order must follow Makerspace -> Device -> Command/Job -> request -> machine/consumables.
- Origin detail resolution hardcodes pk. All new detail URLs use <uuid:pk>, not binding_id/job_id/command_id kwargs.
- No new module, feature, action, notification, scheduler or public route is needed in 7b. Devices module and MANAGE_DEVICES are already registered.
- Settings policy is an ENV_SURFACE list with generated EXCLUDED policies. test_env_surface_drift has no literal device setting pin; add explicit default/policy assertions rather than a nonexistent pin.
- No frontend UI is in this slice (7d owns it); generated schema artifacts are coordinator-owned per lane instructions.

## Plan defects and corrections

1. PrinterJobConsumption cannot use MachineConsumablePool as the input consumed by complete/fail. service_consumption expects machine_consumable_id referencing MachineConsumable, plus quantity. Store typed MachineConsumable inputs with a nullable live FK and source snapshot; reserved MachineConsumablePool reconciliation remains actual_grams/actual_quantity on the job.
2. Binding Machine FK must be nullable SET_NULL, too: a mandatory/protected FK would block machines purge, while CASCADE would delete device provenance. Lease/ack cancels undeliverable jobs; telemetry/result refuses unavailable targets, and no snapshot is used to locate live targets.
3. Pin DeviceCommand.device_key_version at creation. Rechecking only the currently authenticated principal does not stop a rotated key adopting an old acknowledged command. Recovery quarantine already bumps device key_version; the same pin invalidates restored ownership without replaying work.
4. Request title is member-authored free text and may contain PII. Do not copy it into durable request-name snapshots. Use a generic Request <id> label. Free-text failure_reason is a scoped encrypted source field; add encryption registry and count guards, contrary to the plan's no-PII assumption.
5. Lease timeout mutations must commit even when ack returns an error. Do not raise within the transaction after marking expiry/cancellation; return the typed error after commit. Matching ack replay is allowed after acknowledgement without the short lease deadline.
6. Reserve terminal operation IDs per device using a DB unique constraint; check conflicts across jobs. Fingerprint the validated canonical payload (sorted typed consumptions), rejecting unknown fields including price/amount/currency/payment status. Same report never invokes workflow again automatically; staff can explicitly retry needs_review.
7. Terminal report/consumption payload needs database immutability after claim, including queryset/raw writes. Add guards permitting only lifecycle/telemetry updates and controlled purge/adapter SET_NULL edges. Live request state is rechecked before manual/automatic application.
8. Failure workflow's non-weight reconciliation computes actual_quantity from percent_complete; weight failure consumes actual_grams. Validate the reported metering shape against the current request before claim, and pass only the supported reconciliation argument.
9. Portable import needs conditional lifecycle projection: cancel commands regardless of delivery state, turn reported/awaiting work inert, preserve applied history, disable binding and auto-apply. Lease digest is omitted everywhere. Full deployment restore keeps raw rows and invalidates ownership through 7a quarantine; these contracts must not be conflated.
10. Projection/authority declarations must cover lease credentials, key-version pins, report hashes, operation IDs and source snapshot columns, plus relational uniqueness. Add independent guard and round-trip tests; The lane has no Django installation: reconstruct the reviewed literal graph, reproduce the original pin before adding the four independently declared schemas, and leave actual-model digest validation to the coordinator.
11. DeviceEvent existing operation_id is an event identity, not the job report operation. Keep both separate; typed audit job/command/machine/request references use top-level allowlisted fields and never contain arbitrary report/telemetry input.
12. Existing pricing service reads current MakerspaceMachineTypePricing; there is no pricing snapshot contract in this function. Reuse it unchanged, do not invent device pricing or claim a snapshot is used.
13. Application failure handling must not log PII or mask admission errors. Admission checks raise before workflow; workflow exceptions roll back all effects and are recorded in a new source-gated transaction using a constant error code.

14. Both portable row planning and raw dump reset used scalar-only condition matching. In addition, the raw dump defaulted mixed preserve/reset rules to preservation. Reuse row_conditions.condition_matches and select the reset branch for matching target conditions; test every job state in both paths.
15. data_export.guards.py is exactly 300 lines. Split the credential guard before adding explicit non-credential decisions for job state, telemetry state and report hash; retain its public imports.
16. Free-text PII needs a database write-fence trigger, not only the model mixin. Add that trigger, its encryption migration dependency, preflight fence acquisition before domain rows, and closed-fence tests. Authorized PII ciphertext maintenance is allowed; application still checks the plaintext report hash.
17. Transaction B includes the applied marker and its audit/Event writes. Catch errors from the entire effect/marker/provenance boundary, not only the workflow call, and test rollback of consumption and payment when provenance fails.

## Section 7 defect-class checklist

Actor FKs unchanged; model/export/encryption/tenant/backup/purge/origin/uniqueness catalogs enumerated; no module/feature/default-role changes; all-of adapter module guards; module-off 400/tombstone 404; restore invalidates old key ownership; portable projection distinct from deployment backup; audit UUID strings; trigger failure tests use savepoints; migration fixtures enable modules explicitly; no API-client registry edits; pk kwargs; no nullable joined FOR UPDATE.

## Validation limits

No DB-backed suite may run in this lane. Coordinator must run focused and existing workflow/catalog/backup/tombstone tests and regenerate OpenAPI. codex doctor reports configuration/home unavailable and inference unreachable, so an independent external Codex review is coordinator work. No owner product choice blocks the corrected implementation: review remains default-off automatic application.

## Outside-slice defects noted

- The existing Compose environment maps do not forward device tuning keys, including phase 7a knobs. Backend process environment overrides work, and shipped defaults work, but changing root .env alone does not forward these knobs. Compose forwarding is coordinator work; no container stack was run or edited here.
- Existing machine-service failure handling also stores the supplied reason in plaintext MachineServiceRequest.reason and, for reserved pools, MachineConsumableAdjustment.reason. This is an existing workflow/privacy boundary, left untouched per the explicit reuse-only plan. The new PrinterJob copy is encrypted and adapter audit metadata contains no reason.
