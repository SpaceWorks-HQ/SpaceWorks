"""Preserve the legacy public holder-name behaviour for existing makerspaces."""

from django.db import migrations, models


def enable_holder_names(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    # This is unconditional: a currently stats-disabled space will publish names
    # if it enables stats later, unless its manager turns this setting off first.
    Makerspace.objects.all().update(public_stats_show_holder_names=True)


def disable_holder_names(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    Makerspace.objects.all().update(public_stats_show_holder_names=False)


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0059_memberprofile_show_attended_events")]

    operations = [
        migrations.AddField(
            model_name="makerspace",
            name="public_stats_show_holder_names",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(enable_holder_names, disable_holder_names),
    ]
