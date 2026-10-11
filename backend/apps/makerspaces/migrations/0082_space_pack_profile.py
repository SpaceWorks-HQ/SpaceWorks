from django.db import migrations, models
import apps.makerspaces.models_space_packs


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0081_makerspace_loan_policy")]

    operations = [
        migrations.CreateModel(
            name="SpacePackProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("pack", models.JSONField(validators=[apps.makerspaces.models_space_packs.validate_space_pack])),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["name", "pk"]},
        ),
    ]
