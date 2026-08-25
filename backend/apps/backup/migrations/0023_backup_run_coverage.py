import uuid

import django.db.models.deletion
from django.db import migrations, models


RUN_FREEZE_SQL = """
CREATE OR REPLACE FUNCTION backup_run_freeze_fields_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.flag_snapshot <> '{}'::jsonb
       AND NEW.flag_snapshot IS DISTINCT FROM OLD.flag_snapshot THEN
        RAISE EXCEPTION 'immutable backup run flag_snapshot cannot be updated';
    END IF;

    IF OLD.cohort_at IS NOT NULL
       AND NEW.cohort_at IS DISTINCT FROM OLD.cohort_at THEN
        RAISE EXCEPTION 'immutable backup run cohort_at cannot be updated';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER backup_backuprun_freeze_fields
BEFORE UPDATE ON backup_backuprun
FOR EACH ROW EXECUTE FUNCTION backup_run_freeze_fields_guard();
"""


COVERAGE_FREEZE_SQL = """
CREATE OR REPLACE FUNCTION backup_runcoverage_freeze_fields_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.path IS DISTINCT FROM OLD.path
       OR (
           NEW.archive_id IS DISTINCT FROM OLD.archive_id
           AND NEW.archive_id IS NOT NULL
       )
       OR (
           NEW.makerspace_id IS DISTINCT FROM OLD.makerspace_id
           AND NEW.makerspace_id IS NOT NULL
       ) THEN
        RAISE EXCEPTION 'immutable backup run coverage binding cannot be updated';
    END IF;

    IF OLD.makerspace_id_snapshot IS NOT NULL
       AND NEW.makerspace_id_snapshot IS DISTINCT FROM OLD.makerspace_id_snapshot THEN
        RAISE EXCEPTION 'immutable backup run coverage makerspace snapshot cannot be updated';
    END IF;

    IF OLD.archive_id_snapshot IS NOT NULL
       AND NEW.archive_id_snapshot IS DISTINCT FROM OLD.archive_id_snapshot THEN
        RAISE EXCEPTION 'immutable backup run coverage archive snapshot cannot be updated';
    END IF;

    IF OLD.archive_sha256_snapshot <> ''
       AND NEW.archive_sha256_snapshot IS DISTINCT FROM OLD.archive_sha256_snapshot THEN
        RAISE EXCEPTION 'immutable backup run coverage digest snapshot cannot be updated';
    END IF;

    IF OLD.completed_at_snapshot IS NOT NULL
       AND NEW.completed_at_snapshot IS DISTINCT FROM OLD.completed_at_snapshot THEN
        RAISE EXCEPTION 'immutable backup run coverage completion snapshot cannot be updated';
    END IF;

    IF NEW.state IS DISTINCT FROM OLD.state
       AND NOT (OLD.state = 'pending' AND NEW.state = 'covered') THEN
        RAISE EXCEPTION 'backup run coverage state may only advance pending to covered';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER backup_backupruncoverage_freeze_fields
BEFORE UPDATE ON backup_backupruncoverage
FOR EACH ROW EXECUTE FUNCTION backup_runcoverage_freeze_fields_guard();
"""


REVERSE_FREEZE_SQL = """
DROP TRIGGER IF EXISTS backup_backupruncoverage_freeze_fields
ON backup_backupruncoverage;
DROP FUNCTION IF EXISTS backup_runcoverage_freeze_fields_guard();
DROP TRIGGER IF EXISTS backup_backuprun_freeze_fields ON backup_backuprun;
DROP FUNCTION IF EXISTS backup_run_freeze_fields_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("backup", "0022_target_import_recovery_mode"),
    ]

    operations = [
        migrations.CreateModel(
            name="BackupRun",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("cohort_at", models.DateTimeField()),
                ("flag_snapshot", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("complete", "Complete"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("failure_detail", models.CharField(blank=True, max_length=500)),
                ("holder", models.UUIDField(blank=True, null=True)),
                ("leased_until", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        models.Value(1),
                        condition=models.Q(status__in=("pending", "running")),
                        name="uniq_open_backup_run",
                    )
                ]
            },
        ),
        migrations.CreateModel(
            name="BackupRunCoverage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "path",
                    models.CharField(
                        choices=[("global", "Global"), ("tenant", "Tenant")],
                        max_length=16,
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[("pending", "Pending"), ("covered", "Covered")],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("makerspace_id_snapshot", models.BigIntegerField()),
                ("archive_id_snapshot", models.UUIDField(blank=True, null=True)),
                ("archive_sha256_snapshot", models.CharField(blank=True, max_length=64)),
                ("completed_at_snapshot", models.DateTimeField(blank=True, null=True)),
                (
                    "archive",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="run_coverages",
                        to="backup.backuparchive",
                    ),
                ),
                (
                    "makerspace",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="backup_run_coverages",
                        to="makerspaces.makerspace",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="coverage_rows",
                        to="backup.backuprun",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("run", "makerspace_id_snapshot"),
                        name="uniq_backup_run_makerspace_coverage",
                    )
                ]
            },
        ),
        migrations.RunSQL(
            sql=RUN_FREEZE_SQL + COVERAGE_FREEZE_SQL,
            reverse_sql=REVERSE_FREEZE_SQL,
        ),
    ]
