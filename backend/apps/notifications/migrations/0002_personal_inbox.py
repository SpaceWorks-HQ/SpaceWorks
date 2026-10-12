from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="NotificationInboxRow",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("feature", models.CharField(max_length=32)),
                ("event", models.CharField(max_length=64)),
                ("event_key", models.UUIDField()),
                ("title", models.TextField()),
                ("summary", models.TextField(blank=True)),
                ("link", models.CharField(blank=True, max_length=300)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at", "-pk"],
                "indexes": [models.Index(fields=["makerspace", "user", "read_at", "-created_at"], name="personal_inbox_unread_idx")],
                "constraints": [models.UniqueConstraint(fields=["makerspace", "user", "event_key"], name="uniq_personal_inbox_event")],
            },
        ),
        migrations.CreateModel(
            name="MemberNotificationPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("feature", models.CharField(max_length=32)),
                ("channel", models.CharField(max_length=16)),
                ("enabled", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [models.UniqueConstraint(
                fields=["makerspace", "user", "feature", "channel"], name="uniq_member_notify_pref",
            )]},
        ),
    ]
