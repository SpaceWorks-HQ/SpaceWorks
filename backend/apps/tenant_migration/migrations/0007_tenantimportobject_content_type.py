from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenant_migration", "0006_import_objects_and_actor"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantimportobject",
            name="content_type",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
