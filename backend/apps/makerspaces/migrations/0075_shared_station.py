import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("makerspaces", "0074_manage_devices_action"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Station",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("event_checkin", "Event check-in"), ("scanner", "Scanner"), ("handover", "Handover")], max_length=24)),
                ("name", models.CharField(max_length=160)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_stations", to=settings.AUTH_USER_MODEL)),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stations", to="makerspaces.makerspace")),
            ],
        ),
        migrations.CreateModel(
            name="StationCredential",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("pin_digest", models.CharField(editable=False, max_length=128)),
                ("pin_ciphertext", models.BinaryField(editable=False)),
                ("version", models.PositiveIntegerField(default=1, editable=False)),
                ("is_enabled", models.BooleanField(default=True)),
                ("rotated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("disabled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("station", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="credential", to="makerspaces.station")),
            ],
        ),
        migrations.AddConstraint(
            model_name="station",
            constraint=models.UniqueConstraint(fields=("makerspace", "kind", "name"), name="uniq_station_name_per_space_kind"),
        ),
    ]
