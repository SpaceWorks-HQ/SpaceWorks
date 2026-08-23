from django.db import migrations


def backfill_activation(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    Activation = apps.get_model("backup", "B1ActivationState")
    rows = [
        Activation(
            makerspace_id=makerspace_id,
            state="on" if enabled else "off_pending",
        )
        for makerspace_id, enabled in Makerspace.objects.order_by("pk").values_list(
            "pk", "superadmin_access_enabled"
        )
    ]
    Activation.objects.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("backup", "0012_b1_artifact_operational_ledger")]

    operations = [migrations.RunPython(backfill_activation, migrations.RunPython.noop)]
