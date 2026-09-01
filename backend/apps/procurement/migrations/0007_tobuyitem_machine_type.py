import django.db.models.deletion
from django.db import migrations, models


def backfill_machine_type(apps, schema_editor):
    ToBuyItem = apps.get_model("procurement", "ToBuyItem")
    queryset = ToBuyItem.objects.select_related(
        "resulting_machine__machine_type",
        "source_pool__machine__machine_type",
        "resulting_pool__machine__machine_type",
    )
    for item in queryset.iterator():
        machine_type_id = None
        if item.resulting_machine_id is not None:
            machine_type_id = item.resulting_machine.machine_type_id
        elif item.source_pool_id is not None and item.source_pool.machine_id is not None:
            machine_type_id = item.source_pool.machine.machine_type_id
        elif item.resulting_pool_id is not None and item.resulting_pool.machine_id is not None:
            machine_type_id = item.resulting_pool.machine.machine_type_id
        if machine_type_id is not None:
            ToBuyItem.objects.filter(pk=item.pk).update(machine_type_id=machine_type_id)


def clear_machine_type(apps, schema_editor):
    apps.get_model("procurement", "ToBuyItem").objects.update(machine_type_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ("machines", "0020_backfill_role_machine_scope"),
        ("procurement", "0006_kernel_printing_references"),
    ]

    operations = [
        migrations.AddField(
            model_name="tobuyitem",
            name="machine_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="to_buy_items",
                to="machines.machinetype",
            ),
        ),
        migrations.RunPython(backfill_machine_type, clear_machine_type),
    ]
