from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0014_event_registration_cutoff"),
    ]

    operations = [
        migrations.AlterField(
            model_name="eventregistration",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending_approval", "Pending approval"),
                    ("registered", "Registered"),
                    ("waitlisted", "Waitlisted"),
                    ("rejected", "Rejected"),
                    ("cancelled", "Cancelled"),
                    ("attended", "Attended"),
                ],
                default="registered",
                max_length=20,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="eventregistration",
            name="uniq_active_event_registration_member",
        ),
        migrations.AddConstraint(
            model_name="eventregistration",
            constraint=models.UniqueConstraint(
                fields=("event", "member"),
                condition=Q(
                    member__isnull=False,
                    status__in=("pending_approval", "registered", "waitlisted"),
                ),
                name="uniq_active_event_registration_member",
            ),
        ),
    ]
