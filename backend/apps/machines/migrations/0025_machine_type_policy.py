from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("machines", "0024_certifications")]
    operations = [migrations.CreateModel(
        name="MakerspaceMachineTypePolicy",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("cert_reminder_days", models.PositiveSmallIntegerField(blank=True, null=True)),
            ("reminder_lead_days", models.PositiveSmallIntegerField(blank=True, null=True)),
            ("grace_days", models.PositiveSmallIntegerField(blank=True, null=True)),
            ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
            ("machine_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="machines.machinetype")),
        ],
        options={"constraints": [models.UniqueConstraint(
            fields=("makerspace", "machine_type"), name="machine_type_policy_unique",
        )]},
    )]
