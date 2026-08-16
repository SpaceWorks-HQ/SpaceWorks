"""Add machine-type scope and public visibility to consumable pools.

No data migration is needed for ``is_public``: PostgreSQL applies the
``BooleanField(default=True)`` value to existing rows while adding the non-null column,
so a separate ``RunPython`` backfill would be redundant.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("machines", "0020_backfill_role_machine_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="machineconsumablepool",
            name="machine_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="consumable_pools",
                to="machines.machinetype",
            ),
        ),
        migrations.AddField(
            model_name="machineconsumablepool",
            name="is_public",
            field=models.BooleanField(default=True),
        ),
        migrations.AddConstraint(
            model_name="machineconsumablepool",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(machine__isnull=True)
                    | models.Q(machine_type__isnull=True)
                ),
                name="consumable_pool_single_scope",
            ),
        ),
    ]
