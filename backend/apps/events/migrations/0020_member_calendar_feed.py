from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0019_event_calendar_and_badges"),
        ("makerspaces", "0067_reconcile_anonymous_requests_with_membership"),
    ]

    operations = [
        migrations.CreateModel(
            name="MemberCalendarFeed",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("token_digest", models.BinaryField(max_length=32, unique=True)),
                ("token_hint", models.CharField(max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("rotated_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "membership",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="event_calendar_feed",
                        to="makerspaces.makerspacemembership",
                    ),
                ),
            ],
            options={"ordering": ("membership_id",)},
        )
    ]
