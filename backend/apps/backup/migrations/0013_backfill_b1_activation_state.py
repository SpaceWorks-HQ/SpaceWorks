from django.db import migrations
from django.db.models import Count


def backfill_activation(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    Activation = apps.get_model("backup", "B1ActivationState")
    existing_ids = set(
        Activation.objects.values_list("makerspace_id", flat=True)
    )
    rows = [
        Activation(
            makerspace_id=makerspace_id,
            state="on" if enabled else "off_pending",
        )
        for makerspace_id, enabled in Makerspace.objects.order_by("pk").values_list(
            "pk", "superadmin_access_enabled"
        )
        if makerspace_id not in existing_ids
    ]
    Activation.objects.bulk_create(rows)

    makerspaces = dict(
        Makerspace.objects.values_list("pk", "superadmin_access_enabled")
    )
    activation_counts = dict(
        Activation.objects.values("makerspace_id")
        .annotate(row_count=Count("pk"))
        .values_list("makerspace_id", "row_count")
    )
    if set(activation_counts) != set(makerspaces) or any(
        count != 1 for count in activation_counts.values()
    ):
        raise RuntimeError(
            "Every retained makerspace must have exactly one Lane E activation row."
        )
    activations = dict(
        Activation.objects.values_list("makerspace_id", "state")
    )
    divergent = [
        makerspace_id
        for makerspace_id, enabled in makerspaces.items()
        if activations[makerspace_id] != ("on" if enabled else "off_pending")
    ]
    if divergent:
        raise RuntimeError(
            "Lane E activation backfill found flag/state divergence for makerspaces: "
            + ", ".join(str(item) for item in sorted(divergent))
        )


class Migration(migrations.Migration):
    dependencies = [("backup", "0012_b1_artifact_operational_ledger")]

    operations = [migrations.RunPython(backfill_activation, migrations.RunPython.noop)]
