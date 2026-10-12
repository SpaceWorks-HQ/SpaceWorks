from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("maintenance", "0002_schedule_anchor"), ("machines", "0026_public_detail_materials_intake"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="maintenanceschedule", name="trigger", field=models.CharField(choices=[("days", "Days"), ("usage", "Usage"), ("both", "Days or usage")], default="days", max_length=8)),
        migrations.AddField(model_name="maintenanceschedule", name="usage_hours", field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name="maintenanceschedule", name="job_count", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="maintenanceschedule", name="meter_started_at", field=models.DateTimeField(default=django.utils.timezone.now, editable=False)),
        migrations.AddConstraint(model_name="maintenanceschedule", constraint=models.CheckConstraint(condition=models.Q(trigger__in=["days", "usage", "both"]), name="maintenance_trigger_valid")),
        migrations.AddConstraint(model_name="maintenanceschedule", constraint=models.CheckConstraint(condition=models.Q(usage_hours__isnull=True) | models.Q(usage_hours__gt=0), name="maintenance_usage_positive")),
        migrations.AddConstraint(model_name="maintenanceschedule", constraint=models.CheckConstraint(condition=models.Q(job_count__isnull=True) | models.Q(job_count__gt=0), name="maintenance_jobs_positive")),
        migrations.AddConstraint(model_name="maintenanceschedule", constraint=models.CheckConstraint(condition=models.Q(trigger="days") | models.Q(usage_hours__isnull=False) | models.Q(job_count__isnull=False), name="maintenance_meter_required")),
        migrations.CreateModel(name="MaintenanceCalendarFeed", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("token_digest", models.BinaryField(max_length=32, unique=True)),
            ("token_hint", models.CharField(max_length=8)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("revoked_at", models.DateTimeField(blank=True, null=True)),
            ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
            ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ], options={"constraints": [models.UniqueConstraint(fields=("makerspace", "user"), name="maintenance_feed_tenant_user_unique")]}),
    ]
