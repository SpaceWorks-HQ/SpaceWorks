# LANE-PROGRESS — lane `backup`

Branch `lane/backup` off `b7c2ee93`. Plans (gitignored) are in the main checkout at
`docs/plans/2026-10-09-backup-completeness/00-audit.md` and `01-plan.md`.

## Done
- (1) Audit + plan written and saved.
- (2) Offsite destinations: `BackupDestination` + `BackupDestinationUpload` journal (migration
  backup/0025), encrypted credentials, fan-out push with read-back verification against the artifact
  ledger / archive row, bounded backoff, per-destination retention (newest copy protected),
  rehydrate-into-primary, `fetch_offsite_archive` for fresh hosts, superadmin API + `/control/`.

## Mid-flight / next
- (3) `backup` module key; (4) purge_expired_archives fix + tests; OpenAPI regen; docs.

## Tests actually run (./scripts/dev.sh test)
- tests/backup/test_offsite_destinations.py + test_offsite_fetch.py: 16 passed.
- Earlier same session: data_export/test_registry_guards, tenant_migration/test_tenant_dump_catalog_d1,
  test_scheduled_tasks, test_admin_hidden_scope, backup/test_recovery_gate,
  backup/test_object_field_coverage, backup promotion/reconciliation suites: all green after fixes
  (48 passed / 39 passed batches).

## Defect found, not fixed (owner decision)
- `storage_promotion.create_final_from_staging` streams a botocore StreamingBody into `put_object`;
  against real MinIO with botocore 1.43 this raised `io.UnsupportedOperation: seek` (uncaught — not a
  BotoCoreError), and with checksums disabled + ContentLength it raised a ClientError. Every
  deployment-archive promotion against a real S3 store is therefore suspect. Existing tests mock it.
