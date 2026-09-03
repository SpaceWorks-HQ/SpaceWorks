from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0013_eventorganizer"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="registration_requires_approval",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="event",
            name="registration_cutoff_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="event",
            name="registration_cutoff_lead_minutes",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="event",
            constraint=models.CheckConstraint(
                condition=(
                    Q(registration_cutoff_at__isnull=True)
                    | Q(registration_cutoff_lead_minutes__isnull=True)
                ),
                name="event_registration_cutoff_mode_exclusive",
            ),
        ),
        migrations.AddConstraint(
            model_name="event",
            constraint=models.CheckConstraint(
                condition=(
                    Q(registration_cutoff_at__isnull=True)
                    | Q(registration_cutoff_at__lte=F("starts_at"))
                ),
                name="event_registration_cutoff_not_after_start",
            ),
        ),
    ]
