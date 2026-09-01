import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0023_native_app_registrations"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialloginnonce",
            name="attestation_challenge",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="social_login_nonces",
                to="accounts.deviceattestationchallenge",
            ),
        ),
        migrations.AddConstraint(
            model_name="socialloginnonce",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        delivery="web",
                        device_grant__isnull=True,
                        attestation_challenge__isnull=True,
                    )
                    | models.Q(
                        delivery="device",
                        device_grant__isnull=False,
                        attestation_challenge__isnull=True,
                    )
                    | models.Q(
                        delivery="device",
                        device_grant__isnull=True,
                        attestation_challenge__isnull=False,
                    )
                ),
                name="social_nonce_delivery_anchor_ck",
            ),
        ),
    ]
