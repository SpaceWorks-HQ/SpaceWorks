import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0010_event_collaboration_provenance"),
        ("makerspaces", "0041_member_memberships_waivers"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventregistration",
            name="host_waiver",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="accepted_by_event_registrations",
                to="makerspaces.makerspacewaiver",
            ),
        ),
        migrations.AddField(
            model_name="eventregistration",
            name="host_waiver_accepted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="eventregistration",
            name="host_waiver_version_accepted",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddConstraint(
            model_name="eventregistration",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        host_waiver__isnull=True,
                        host_waiver_accepted_at__isnull=True,
                        host_waiver_version_accepted__isnull=True,
                    )
                    | models.Q(
                        host_waiver__isnull=False,
                        host_waiver_accepted_at__isnull=False,
                        host_waiver_version_accepted__isnull=False,
                    )
                ),
                name="event_registration_host_waiver_all_or_none",
            ),
        ),
    ]
