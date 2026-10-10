"""Extend append-only provenance vocabulary; retained rows stay untouched."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("devices", "0001_device_identity")]
    operations = [
        migrations.AlterField(model_name="deviceevent", name="event_type",
                              field=models.CharField(choices=[('created', 'Created'), ('updated', 'Updated'), ('enrollment_created', 'Enrollment created'), ('enrolled', 'Enrolled'), ('rotation_started', 'Rotation started'), ('rotated', 'Rotated'), ('revoked', 'Revoked'), ('heartbeat', 'Heartbeat'), ('offline_detected', 'Offline detected'), ('recovered', 'Recovered')], max_length=32)),
    ]
