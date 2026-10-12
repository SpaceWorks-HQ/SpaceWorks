from django.conf import settings
from django.db import migrations, models

import apps.makerspaces.profile_validation as validation


def backfill_timezone(apps, schema_editor):
    # This deployment's configured zone, not a hard-coded UTC assumption.
    apps.get_model("makerspaces", "Makerspace").objects.using(
        schema_editor.connection.alias
    ).all().update(timezone=settings.TIME_ZONE)


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0076_station_operator_leases")]

    operations = [
        migrations.AddField(
            model_name="makerspace", name="timezone",
            field=models.CharField(max_length=100, default=validation.default_timezone,
                                   validators=[validation.validate_timezone]),
        ),
        migrations.AddField(
            model_name="makerspace", name="country",
            field=models.CharField(max_length=2, blank=True, default="",
                                   validators=[validation.validate_country]),
        ),
        migrations.AddField(
            model_name="makerspace", name="opening_hours",
            field=models.JSONField(default=dict, blank=True,
                                   validators=[validation.validate_opening_hours]),
        ),
        migrations.RunPython(backfill_timezone, migrations.RunPython.noop),
    ]
