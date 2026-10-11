from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("inventory", "0013_product_master_data"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="inventoryproduct", name="borrowing_terms",
                            field=models.TextField(blank=True, max_length=2000)),
        migrations.CreateModel(name="InventoryWatch", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("ready_at", models.DateTimeField(blank=True, null=True)),
            ("notified_at", models.DateTimeField(blank=True, null=True)),
            ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
            ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="inventory.inventoryproduct")),
            ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ], options={"constraints": [models.UniqueConstraint(fields=("product", "user"), name="inventory_watch_product_user_unique")]}),
    ]
