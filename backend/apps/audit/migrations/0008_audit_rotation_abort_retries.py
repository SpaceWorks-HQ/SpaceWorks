import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("audit", "0007_audit_rotation_event_state_order")]

    operations = [
        migrations.AlterField(
            model_name="auditsigningkeyrotation",
            name="old_key",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rotations_from",
                to="audit.auditsigningkey",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="auditsigningkeyrotation",
            name="ck_audit_rotation_adjacent_versions",
        ),
        migrations.AddConstraint(
            model_name="auditsigningkeyrotation",
            constraint=models.CheckConstraint(
                condition=models.Q(new_version__gt=models.F("old_version")),
                name="ck_audit_rotation_increasing_versions",
            ),
        ),
    ]
