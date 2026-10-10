from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("hardware_requests", "0025_kiosk_replay"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField("replaycommand", "resolution_code", models.CharField(
            max_length=24, null=True, blank=True,
            choices=[("acknowledged_no_change", "Acknowledged No Change"), ("replaced_online", "Replaced Online")],
        )),
        migrations.AddField("replaycommand", "resolved_by", models.ForeignKey(
            settings.AUTH_USER_MODEL, null=True, blank=True,
            on_delete=django.db.models.deletion.PROTECT, related_name="resolved_kiosk_replays",
        )),
        migrations.AddField("replaycommand", "resolved_at", models.DateTimeField(null=True, blank=True)),
        migrations.AddField("replaycommand", "replacement_command", models.ForeignKey(
            "hardware_requests.replaycommand", null=True, blank=True,
            on_delete=django.db.models.deletion.PROTECT, related_name="resolved_failures",
        )),
        migrations.AddConstraint("replaycommand", models.CheckConstraint(
            condition=(models.Q(resolution_code__isnull=True, resolved_by__isnull=True,
                                resolved_at__isnull=True, replacement_command__isnull=True)
                       | models.Q(state="failed", resolution_code__isnull=False, resolved_by__isnull=False, resolved_at__isnull=False,
                                  resolution_code="acknowledged_no_change", replacement_command__isnull=True)
                       | models.Q(state="failed", resolution_code__isnull=False, resolved_by__isnull=False, resolved_at__isnull=False,
                                  resolution_code="replaced_online", replacement_command__isnull=False)),
            name="replay_resolution_consistent",
        )),
        migrations.AddConstraint("replaycommand", models.CheckConstraint(
            condition=~models.Q(pk=models.F("replacement_command")), name="replay_replacement_not_self",
        )),
        migrations.AddConstraint("replaycommand", models.UniqueConstraint(
            fields=("replacement_command",), condition=models.Q(replacement_command__isnull=False),
            name="replay_replacement_used_once",
        )),
    ]
