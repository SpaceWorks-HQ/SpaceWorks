# LANE-PROGRESS — lane `backup`

Branch `lane/backup` off `b7c2ee93`. Plans (gitignored) are in the main checkout at
`docs/plans/2026-10-09-backup-completeness/00-audit.md` and `01-plan.md`.

## Done
- (1) Audit + plan written and saved.
- (2) Offsite destinations: `BackupDestination` + `BackupDestinationUpload` journal (backup/0025),
  encrypted credentials, fan-out push with read-back verification against the artifact ledger /
  archive row, bounded backoff (never fails a backup), per-destination retention (newest copy
  protected), create-only rehydration into primary, `fetch_offsite_archive` for fresh hosts,
  superadmin API (7 routes) + `/control/` admin, beat + beat-less schedule entries.
- (3) `backup` module key (default-on, backfill backup/0026, new group), gates tenant archive,
  recipient and new custody routes (400 when off); compromise + deployment surfaces never gated;
  uninstall refused while superadmin access off and vice versa; purge plan (ad hoc archives only);
  docs/MODULES.md, README, registry pin 33→34, contract probe, report coverage; console panel hides
  the makerspace section when off.
- (4) Gaps: purge_expired_archives starvation/no-audit/staging leak fixed + tested;
  cleanup_expired_rollback_objects crash (FOR UPDATE + nullable select_related) fixed + tested.
- OpenAPI + api.ts regenerated; INVARIANTS / SOURCE-MAP / PROJECT-HISTORY updated.

## Not done
- `recover_superadmin` command test (audit 10); restore drills (owner decision); K1 archive import
  (owner decision); Lane D orchestration surface (other app); all-in-one end-to-end test.
- `create_final_from_staging` streaming defect: documented, not fixed (see INVARIANTS).
- tests/tenant_migration full suite not re-run (Lane D catalog digest pin was bumped; its catalog
  test file was run and passes).

## Tests actually run (./scripts/dev.sh test)
- test_offsite_destinations + test_offsite_fetch: 16 passed.
- backup/test_backup_module, makerspaces/test_module_registry(+_groups), modules/test_module_contract_matrix,
  makerspaces/test_module_install, test_lean_profiles, test_module_console, backup/test_archive_api,
  test_archive_recipient_api, test_activation_e6, test_archive_recipients: 161 passed, 18 skipped.
- backup/test_archive_retention_purge + test_object_restore: 7 passed.
- backup/test_archive_retention_purge + test_restore_services + test_archive_expiry: 15 passed (+1 fixed).
- data_export/test_registry_guards, tenant_migration/test_tenant_dump_catalog_d1, test_scheduled_tasks,
  test_admin_hidden_scope, backup/test_recovery_gate, backup/test_object_field_coverage,
  backup promotion/reconciliation suites: green after fixes.
- Frontend: tsc -b clean, npm test 278 passed, npm run build ok.
- Batch tests/backup + tests/modules + tests/makerspaces: see final report.
