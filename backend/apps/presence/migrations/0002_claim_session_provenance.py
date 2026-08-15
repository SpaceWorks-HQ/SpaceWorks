import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0019_memberclaimcode_absolute_expires_at"),
        ("presence", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="presencesession",
            name="created_via_claim_session",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="presence_sessions",
                to="accounts.memberclaimcode",
            ),
        ),
        migrations.AlterField(
            model_name="presencesession",
            name="end_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("superseded", "Superseded"),
                    ("membership_revoked", "Membership revoked"),
                    ("claim_revoked", "Claim revoked"),
                    ("user_ended", "User ended"),
                ],
                max_length=24,
            ),
        ),
    ]
