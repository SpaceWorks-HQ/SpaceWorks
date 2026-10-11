from django.db import migrations, models
import apps.operations.models_report_schedules


class Migration(migrations.Migration):
    dependencies = [("operations", "0011_saved_view")]

    operations = [
        migrations.AddField(model_name="reportschedule", name="condition", field=models.JSONField(
            blank=True, default=dict, validators=[apps.operations.models_report_schedules.validate_schedule_filters],
        )),
        migrations.AddField(model_name="reportschedule", name="recipient_roles", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="reportschedule", name="recipient_actions", field=models.JSONField(blank=True, default=list)),
    ]
