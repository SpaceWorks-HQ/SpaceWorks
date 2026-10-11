from django.db import migrations, models
from apps.inventory.kit_validators import validate_kit_definition


class Migration(migrations.Migration):
    dependencies = [("boxes", "0010_member_cards")]
    operations = [migrations.AddField(
        model_name="box", name="kit_components", field=models.JSONField(default=list, blank=True,
                                                                      validators=[validate_kit_definition]),
    )]
