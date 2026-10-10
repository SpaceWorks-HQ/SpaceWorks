from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0028_research_notification_families"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField("emaillog", "recipient", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name="notification_email_logs", to=settings.AUTH_USER_MODEL,
        )),
        migrations.AddField("emaillog", "feature", models.CharField(blank=True, max_length=32)),
        migrations.AddField("emaillog", "retry_generation", models.PositiveIntegerField(default=0)),
        migrations.AddField("notificationdeliverylog", "retry_generation", models.PositiveIntegerField(default=0)),
        migrations.AddField("notificationdestination", "payload_version", models.PositiveSmallIntegerField(
            choices=[(1, "Legacy"), (2, "Structured")], default=1,
        )),
        migrations.AlterField("notificationpreference", "channel", models.CharField(
            max_length=16, choices=[("in_app", "Inbox"), ("email", "Email"), ("telegram", "Telegram"),
            ("slack", "Slack"), ("mattermost", "Mattermost"), ("discord", "Discord"),
            ("webhook", "Signed webhook"), ("native_push", "Native push")],
        )),
        migrations.CreateModel(
            name="EmailSuppression",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("address_hash", models.CharField(max_length=64)),
                ("reason", models.CharField(choices=[("bounce", "Hard bounce"), ("complaint", "Spam complaint")], max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("makerspace", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [models.UniqueConstraint(
                fields=["makerspace", "address_hash"], name="uniq_space_suppressed_email",
            ), models.UniqueConstraint(
                fields=["address_hash"], condition=models.Q(makerspace__isnull=True),
                name="uniq_platform_suppressed_email",
            )]},
        ),
    ]
