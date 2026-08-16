from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0018_memberclaimcode")]

    operations = [
        migrations.AddField(
            model_name="memberclaimcode",
            name="absolute_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
