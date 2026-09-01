import django.db.models.deletion
from django.db import migrations, models


ARCHIVE_FREEZE_SQL = """
CREATE OR REPLACE FUNCTION backup_archive_freeze_fields_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.backup_run_id IS NOT NULL
       AND NEW.backup_run_id IS DISTINCT FROM OLD.backup_run_id THEN
        RAISE EXCEPTION 'immutable backup archive backup_run cannot be updated';
    END IF;

    IF OLD.status <> 'pending'
       AND NEW.backup_run_id IS DISTINCT FROM OLD.backup_run_id THEN
        RAISE EXCEPTION 'backup archive backup_run cannot change after claim';
    END IF;

    IF OLD.superadmin_access_at_decision IS NOT NULL
       AND NEW.superadmin_access_at_decision IS DISTINCT FROM
           OLD.superadmin_access_at_decision THEN
        RAISE EXCEPTION 'immutable backup archive access decision cannot be updated';
    END IF;

    IF OLD.expires_at IS NOT NULL
       AND NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
        RAISE EXCEPTION 'immutable backup archive expiry cannot be updated';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER backup_backuparchive_freeze_fields
BEFORE UPDATE ON backup_backuparchive
FOR EACH ROW EXECUTE FUNCTION backup_archive_freeze_fields_guard();
"""


REVERSE_ARCHIVE_FREEZE_SQL = """
DROP TRIGGER IF EXISTS backup_backuparchive_freeze_fields
ON backup_backuparchive;
DROP FUNCTION IF EXISTS backup_archive_freeze_fields_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("backup", "0023_backup_run_coverage"),
    ]

    operations = [
        migrations.AddField(
            model_name="backuparchive",
            name="backup_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="archives",
                to="backup.backuprun",
            ),
        ),
        migrations.AddField(
            model_name="backuparchive",
            name="build_holder",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="backuparchive",
            name="staging_object_key",
            field=models.CharField(blank=True, max_length=512, null=True),
        ),
        migrations.AlterField(
            model_name="backuparchive",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="backuparchive",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("running", "Running"),
                    ("promoting", "Promoting"),
                    ("available", "Available"),
                    ("failed", "Failed"),
                    ("expired", "Expired"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.RunSQL(
            sql=(
                "UPDATE backup_backuparchive SET expires_at = NULL "
                "WHERE status IN ('pending', 'running');"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddConstraint(
            model_name="backuparchive",
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(status="available")
                    | models.Q(expires_at__isnull=False)
                ),
                name="backup_available_requires_expiry",
            ),
        ),
        migrations.RunSQL(
            sql=ARCHIVE_FREEZE_SQL,
            reverse_sql=REVERSE_ARCHIVE_FREEZE_SQL,
        ),
    ]
