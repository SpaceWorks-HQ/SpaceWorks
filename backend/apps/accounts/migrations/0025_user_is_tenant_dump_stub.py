from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0024_social_nonce_attestation_challenge")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_tenant_dump_stub",
            field=models.BooleanField(default=False),
        ),
    ]
