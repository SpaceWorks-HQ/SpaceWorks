from django.db import migrations, models
from apps.inventory.kit_validators import validate_kit_definition


class Migration(migrations.Migration):
    dependencies = [("inventory", "0012_loan_period_overrides")]

    operations = [
        migrations.AddField(model_name="inventoryproduct", name=name,
                            field=models.CharField(max_length=length, blank=True))
        for name, length in (("manufacturer", 200), ("model", 200), ("sku", 100),
                             ("barcode", 100), ("supplier", 200))
    ] + [
        migrations.AddField(model_name="inventoryproduct", name="reorder_point",
                            field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="inventoryproduct", name="reorder_quantity",
                            field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="inventoryproduct", name="kit_components",
                            field=models.JSONField(default=list, blank=True, validators=[validate_kit_definition])),
    ]
