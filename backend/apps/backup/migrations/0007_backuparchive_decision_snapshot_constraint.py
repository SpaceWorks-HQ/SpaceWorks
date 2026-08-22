from django.db import migrations, models


class Migration(migrations.Migration):
    """Install the snapshot constraint in its own transaction.

    Separated from 0006 on purpose: that migration updates existing rows, and
    PostgreSQL rejects `ALTER TABLE ... ADD CONSTRAINT` while those UPDATEs still
    have pending trigger events in the same transaction.
    """

    dependencies = [
        ("backup", "0006_backuparchive_decision_snapshot_guard"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="backuparchive",
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(scope="makerspace")
                    | models.Q(superadmin_access_at_decision__isnull=False)
                    | models.Q(legacy_pre_decision_snapshot=True)
                ),
                name="backup_makerspace_decision_snapshot_present",
            ),
        ),
    ]
