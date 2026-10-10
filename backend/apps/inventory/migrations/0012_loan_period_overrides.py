from django.db import migrations, models
from django.core.validators import MinValueValidator, MaxValueValidator


class Migration(migrations.Migration):
    dependencies = [("inventory", "0011_inventoryproduct_deposit_amount")]
    operations = [
        migrations.AddField(model_name=model, name=name, field=field)
        for model in ("category", "inventoryproduct")
        for name, field in (
            ("loan_days", models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(365)])),
            ("max_renewals", models.PositiveIntegerField(null=True, blank=True, validators=[MaxValueValidator(100)])),
        )
    ]
