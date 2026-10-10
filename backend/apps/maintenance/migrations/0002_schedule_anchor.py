from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("maintenance", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="maintenanceschedule", name="anchor",
            field=models.CharField(choices=[("completion", "Completion date"), ("calendar", "Fixed calendar")], default="completion", max_length=16),
        ),
        migrations.AddConstraint(
            model_name="maintenanceschedule",
            constraint=models.CheckConstraint(condition=models.Q(anchor__in=["completion", "calendar"]), name="maintenance_anchor_valid"),
        ),
    ]
