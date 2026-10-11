from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("procurement", "0007_tobuyitem_machine_type"),
                    ("inventory", "0013_product_master_data")]
    operations = [migrations.AddField(
        model_name="tobuyitem", name="source_product",
        field=models.ForeignKey(to="inventory.inventoryproduct", null=True, blank=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="reorder_drafts"),
    )]
