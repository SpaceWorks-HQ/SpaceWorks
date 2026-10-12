from django.db import migrations, models


def preserve_publication_and_loans(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for space in Makerspace.objects.using(schema_editor.connection.alias).iterator():
        features = list(space.enabled_features or [])
        if "loans.enabled" not in features:
            features.append("loans.enabled")
        Makerspace.objects.using(schema_editor.connection.alias).filter(pk=space.pk).update(
            public_site_enabled=space.public_inventory_enabled, enabled_features=features,
        )


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0085_space_pack_profile")]
    operations = [
        migrations.AddField(
            model_name="makerspace", name="public_site_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="makerspace", name="public_landing_page",
            field=models.CharField(max_length=16, default="auto", choices=[
                ("auto", "Auto"), ("inventory", "Inventory"), ("events", "Events"),
                ("machines", "Machines"), ("bookings", "Bookings"), ("membership", "Membership"),
            ]),
        ),
        migrations.RunPython(preserve_publication_and_loans, migrations.RunPython.noop),
    ]
