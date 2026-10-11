from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [("operations", "0012_report_schedule_rules")]
    operations = [
        migrations.AddField(model_name="stocktakesession", name="blind", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="stocktakesession", name="variance_threshold", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="stocktakesession", name="approval_required", field=models.BooleanField(default=True)),
        migrations.CreateModel(name="StocktakePolicy", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("blind_default", models.BooleanField(default=False)),
            ("variance_threshold", models.PositiveIntegerField(blank=True, null=True)),
            ("makerspace", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
        ]),
        migrations.CreateModel(name="StocktakeSchedule", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=200)),
            ("interval_days", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
            ("next_due", models.DateField()),
            ("blind", models.BooleanField(default=False)),
            ("is_active", models.BooleanField(default=True)),
            ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
            ("container", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="boxes.box")),
        ], options={"constraints": [models.CheckConstraint(condition=models.Q(interval_days__gt=0), name="stocktake_schedule_interval_positive")]}),
    ]
