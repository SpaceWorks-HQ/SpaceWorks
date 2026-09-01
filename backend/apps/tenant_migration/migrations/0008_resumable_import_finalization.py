from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenant_migration", "0007_tenantimportobject_content_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantimportjob",
            name="materialization_report",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="tenantimportjob",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("awaiting_identity", "Awaiting identity decisions"),
                    ("ready", "Ready"),
                    ("materializing", "Materializing"),
                    ("finalizing", "Finalizing"),
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                    ("abandoned", "Abandoned"),
                ],
                default="pending",
                max_length=32,
            ),
        ),
    ]
