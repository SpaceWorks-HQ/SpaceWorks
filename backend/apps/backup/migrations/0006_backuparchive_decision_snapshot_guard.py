from django.db import migrations, models
from django.utils import timezone


def classify_archives_without_decision_snapshot(apps, schema_editor):
    BackupArchive = apps.get_model("backup", "BackupArchive")
    missing_snapshot = BackupArchive.objects.using(
        schema_editor.connection.alias
    ).filter(
        scope="makerspace",
        superadmin_access_at_decision__isnull=True,
    )
    active_statuses = ("pending", "running")

    # EVERY pre-existing row without a snapshot carries legacy provenance -- including
    # the ones failed below. The constraint added after this step permits a NULL
    # snapshot only for legacy rows, so failing an archive without also marking it
    # legacy would leave it violating that constraint and abort the migration.
    missing_snapshot.update(legacy_pre_decision_snapshot=True)
    missing_snapshot.filter(status__in=active_statuses).update(
        status="failed",
        failure_detail="legacy_decision_snapshot_absent",
        completed_at=timezone.now(),
    )


# The CheckConstraint deliberately lives in the NEXT migration. PostgreSQL refuses
# `ALTER TABLE ... ADD CONSTRAINT` in the same transaction as preceding DML on that
# table -- it fails with "cannot ALTER TABLE because it has pending trigger events"
# as soon as there are rows for the RunPython above to update. Splitting the DDL into
# its own migration gives the data changes their own committed transaction.
class Migration(migrations.Migration):

    dependencies = [
        ("backup", "0005_backuparchive_superadmin_access_at_decision"),
    ]

    operations = [
        migrations.AddField(
            model_name="backuparchive",
            name="legacy_pre_decision_snapshot",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            classify_archives_without_decision_snapshot,
            migrations.RunPython.noop,
        ),
    ]
