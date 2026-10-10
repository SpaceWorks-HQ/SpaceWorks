from django.db import migrations, models
import django.core.validators
import apps.makerspaces.models_loan_policy


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0079_staff_invitations_feature")]

    operations = [
        migrations.CreateModel(
            name="MakerspaceLoanPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("makerspace", models.OneToOneField(on_delete=models.CASCADE, related_name="loan_policy", to="makerspaces.makerspace")),
                ("default_loan_days", models.PositiveIntegerField(default=7, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(365)])),
                ("loan_renewal_mode", models.CharField(choices=[("off", "Off"), ("auto", "Automatic within policy")], default="off", max_length=16)),
                ("loan_max_renewals", models.PositiveIntegerField(default=1, validators=[django.core.validators.MaxValueValidator(100)])),
                ("loan_renewal_days", models.PositiveIntegerField(default=7, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(365)])),
                ("loan_max_active", models.PositiveIntegerField(default=0)),
                ("loan_max_items", models.PositiveIntegerField(default=0)),
                ("loan_reminder_offsets_hours", models.JSONField(default=apps.makerspaces.models_loan_policy.default_reminder_offsets, validators=[apps.makerspaces.models_loan_policy.validate_reminder_offsets])),
                ("loan_escalate_overdue_days", models.PositiveIntegerField(default=0, validators=[django.core.validators.MaxValueValidator(365)])),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(model_name="membershipplan", name="loan_max_active", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="membershipplan", name="loan_max_items", field=models.PositiveIntegerField(blank=True, null=True)),
    ]
