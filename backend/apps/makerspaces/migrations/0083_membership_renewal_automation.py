"""Optional plan automation and one-to-one successor provenance."""
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import apps.makerspaces.models_membership_plans


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0082_event_booking_reminder_policy")]

    operations = [
        migrations.AddField("makerspacemembership", "renewal_cancelled_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("membershipplan", "auto_renew", models.BooleanField(default=False)),
        migrations.AddField("membershipplan", "renewal_open_days", models.PositiveSmallIntegerField(default=7, validators=[django.core.validators.MaxValueValidator(365)])),
        migrations.AddField("membershipplan", "renewal_grace_days", models.PositiveSmallIntegerField(default=0, validators=[django.core.validators.MaxValueValidator(365)])),
        migrations.AddField("membershipplan", "renewal_retries", models.PositiveSmallIntegerField(default=0, validators=[django.core.validators.MaxValueValidator(3)])),
        migrations.AddField("membershipplan", "reminder_days_before", models.JSONField(blank=True, default=apps.makerspaces.models_membership_plans.default_renewal_reminders)),
        migrations.AddField("membershipplan", "reminder_days_after", models.JSONField(blank=True, default=list)),
        migrations.AddField("membershipterm", "renewed_from", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="next_term", to="makerspaces.membershipterm")),
        migrations.AddField("membershipterm", "renewal_attempts", models.PositiveSmallIntegerField(default=0)),
        migrations.AddField("membershipterm", "renewal_retry_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("membershipterm", "grace_until", models.DateTimeField(blank=True, null=True)),
    ]
