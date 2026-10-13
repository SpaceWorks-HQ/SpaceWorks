# Database recovery after an update

`update.sh` keeps a compressed plain-SQL database dump at
`backups/pre-update-<timestamp>.sql.gz`. An automatic rollback changes application images only.
Forward migrations remain applied; the dump is never restored automatically. Restoring a database
loses database changes made since the dump. The dump contains no uploaded object bytes.

## Inspect a failed deployment

As the install owner, inspect logs before restarting anything:

```bash
bash scripts/spaceworks-compose.sh bundled ps -a
bash scripts/spaceworks-compose.sh bundled logs orchestration-init migrate orchestration-ready backend
```

Use the installation's recorded layer through the wrapper; single-box logs use `app` instead of
`backend`. Failed run-once containers remain for inspection. A successful application-image rollback
leaves `.spaceworks-version` at the previous immutable release. If the previous release is healthy,
no database restoration is normally needed.

If an installer upgrade stopped while replacing its host runtime bundle or refreshing Compose trust
records, the error names a `backups/host-config-*` directory. Keep application writers stopped; as the
install owner, restore the saved runtime files to their original relative paths, then run
`bash scripts/init-host-orchestration.sh` with the installed version's backend image tag to recreate
matching configuration proofs. This is host configuration recovery and does not restore the database.

## Restore a pre-update SQL dump

This is an offline database-owner recovery procedure, separate from verified archive restore.
Do not pass a `.sql.gz` file to `scripts/restore.sh`: that supervisor accepts a recorded restore UUID
and a verified archive, not a SQL dump.

1. Suspend automatic deploys (on systemd, `sudo systemctl stop spaceworks-deploy.path`) and stop any
   non-systemd request-consumer cron. Confirm no updater, backup or restore is running. Keep the shared
   host operation lock held through recovery, using Linux/WSL2 `flock`; do not clear a live lock.
2. Save the failed database and current `.env`, host pointer/configuration and version marker before
   replacing anything. Keep the object-storage volumes and continuity encryption keys unchanged.
3. Confirm the database name and server from the **active host database pointer**, and confirm that
   identity is the database captured by the selected dump. H1 recovery can change that pointer:
   `POSTGRES_DB` is not proof of the live application's database. A database owner must review this
   identity before any drop, create or restore command. Managed/external databases need their provider's
   restore procedure and pointer/CAS adapter; the bundled-container procedure does not apply to them.
4. Stop the whole application stack, including web front, webhook receiver, live streams, workers and
   schedulers. Keep only the database container running. Confirm all writers are disconnected. Check
   the dump's integrity with `gzip -t backups/pre-update-<timestamp>.sql.gz`.
5. As the database owner, recreate the explicitly confirmed target database and stream the decompressed
   SQL into `psql` with `ON_ERROR_STOP=1`. Use the matching client inside the database container. Do not
   import into a database still holding application tables, and do not ignore SQL errors. A partial
   import stays offline until a complete restore succeeds.
6. Reprovision the least-privilege runtime grants for that exact database through the shipped
   orchestration-ready grants-only path (`SPACEWORKS_GRANTS_ONLY=1` and
   `SPACEWORKS_GRANT_DATABASE_NAME=<confirmed database>`). Verify the active pointer still names it.
7. Set the previous immutable release's image tag and `.spaceworks-version`, pull those application
   images, and start through the existing orchestration/migration gates. Check readiness before
   reopening access or restarting the deploy trigger. If grants, host trust, recovery gates or
   readiness refuse startup, keep writers stopped and resolve the refusal.

A SQL-only restore does not reproduce object bytes or rewind object mutations after the dump. For
coordinated database/object recovery use a compatible verified deployment archive and its recovery
workflow. Do not waive the host capability, signature, compatibility or quarantine gates.

## Existing verified archive restore

The backup feature and its independent host supervisor remain. Request/confirm the restore through
its existing backup workflow and obtain the recorded RestoreOperation UUID. For an admitted legacy
in-place restore, run on Linux/WSL2 with the configured age identity and required host privileges:

```bash
sudo bash scripts/restore.sh <restore-uuid>
```

The supervisor verifies the archive and compatibility before destructive changes, drains writers,
takes its own pre-restore snapshot, restores the database and objects, reprovisions grants, and checks
readiness/recovery state. Follow any restore-diff decision in the backup console. A disaster/reset
restore enters quarantine: run the existing superadmin recovery workflow and acknowledge residual risk
before allowing normal writes. Interrupted destructive work uses its durable rollback journal.

`restore.sh` is the legacy path and refuses compound envelopes, including envelopes without sovereign
slices, and unsupported single-box restore. Compound archives require their supported host coordinator;
do not force them through the legacy supervisor or treat a verified offsite copy as a proven restore.
