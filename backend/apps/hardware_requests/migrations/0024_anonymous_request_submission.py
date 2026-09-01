from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hardware_requests", "0023_scoped_pii_text_fields")]

    operations = [
        migrations.AddField(
            model_name="hardwarerequest",
            name="anonymous_idempotency_key_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="hardwarerequest",
            name="anonymous_payload_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="hardwarerequest",
            name="requester_contact_verified",
            field=models.BooleanField(default=True),
        ),
        migrations.AddIndex(
            model_name="hardwarerequest",
            index=models.Index(
                condition=(
                    models.Q(status="pending_approval")
                    & ~models.Q(anonymous_idempotency_key_fingerprint="")
                ),
                fields=["makerspace", "status"],
                name="hwreq_anon_pending_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="hardwarerequest",
            constraint=models.UniqueConstraint(
                condition=~models.Q(anonymous_idempotency_key_fingerprint=""),
                fields=("makerspace", "anonymous_idempotency_key_fingerprint"),
                name="uniq_hwreq_anon_idempotency",
            ),
        ),
    ]
