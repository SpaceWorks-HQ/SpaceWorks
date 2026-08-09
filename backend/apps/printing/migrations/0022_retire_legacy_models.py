from django.db import migrations


LEGACY_MODELS_WITH_DIRECT_MAKERSPACE = (
    "PrintBucket",
    "PrintPrinter",
    "FilamentSpool",
    "FilamentAdjustment",
    "ManualPrintLog",
    "PrintRequestFile",
)


def assert_all_legacy_printing_is_kernel_authoritative(apps, schema_editor):
    """Refuse irreversible table removal until every affected tenant is flipped."""
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    PrintingCutoverState = apps.get_model("machines", "PrintingCutoverState")
    candidates = set(
        Makerspace.objects.filter(enabled_modules__contains=["printing"])
        .values_list("pk", flat=True)
    )
    for model_name in LEGACY_MODELS_WITH_DIRECT_MAKERSPACE:
        model = apps.get_model("printing", model_name)
        candidates.update(model.objects.values_list("makerspace_id", flat=True))
    PrintRequest = apps.get_model("printing", "PrintRequest")
    candidates.update(
        PrintRequest.objects.values_list("bucket__makerspace_id", flat=True)
    )
    candidates.discard(None)
    authoritative = set(
        PrintingCutoverState.objects.filter(
            makerspace_id__in=candidates,
            kernel_authoritative_at__isnull=False,
        ).values_list("makerspace_id", flat=True)
    )
    unflipped = candidates - authoritative
    if unflipped:
        details = ", ".join(
            f"{pk}:{slug}"
            for pk, slug in Makerspace.objects.filter(pk__in=unflipped)
            .order_by("pk")
            .values_list("pk", "slug")
        )
        raise RuntimeError(
            "Cannot retire legacy printing tables; unflipped makerspaces: " + details
        )


class Migration(migrations.Migration):
    dependencies = [
        ("printing", "0021_member_owned_public_uploads"),
        ("procurement", "0006_kernel_printing_references"),
        ("warranty", "0003_remove_printer_host"),
        ("machines", "0015_remove_print_printer_bridge"),
        ("encryption", "0004_pii_write_fence"),
    ]

    operations = [
        migrations.RunPython(
            assert_all_legacy_printing_is_kernel_authoritative,
            migrations.RunPython.noop,
        ),
        migrations.DeleteModel(name="PrintRequestFile"),
        migrations.DeleteModel(name="FilamentAdjustment"),
        migrations.DeleteModel(name="PrintRequest"),
        migrations.DeleteModel(name="ManualPrintLog"),
        migrations.DeleteModel(name="FilamentSpool"),
        migrations.DeleteModel(name="PrintPrinter"),
        migrations.DeleteModel(name="PrintBucket"),
        migrations.RunSQL(
            sql="""
DROP FUNCTION IF EXISTS printing_filament_adjustment_reject_mutation() CASCADE;
DROP FUNCTION IF EXISTS pii_fence_print_request() CASCADE;
DROP FUNCTION IF EXISTS pii_fence_manual_print_log() CASCADE;
""",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
