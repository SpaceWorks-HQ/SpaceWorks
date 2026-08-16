from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("machines", "0021_consumable_pool_type_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="machineconsumablepool",
            name="color_hex",
            field=models.CharField(blank=True, default="", max_length=7),
        ),
        migrations.AddConstraint(
            model_name="machineconsumablepool",
            constraint=models.CheckConstraint(
                condition=models.Q(("color_hex", ""), ("color_hex__regex", r"^#[0-9A-Fa-f]{6}$"), _connector="OR"),
                name="consumable_pool_color_hex_valid",
            ),
        ),
    ]
