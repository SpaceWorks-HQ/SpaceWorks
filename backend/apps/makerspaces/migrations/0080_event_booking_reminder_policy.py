from django.db import migrations, models

from apps.makerspaces.reminder_policy import default_reminder_lead_hours, validate_reminder_lead_hours


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0079_staff_invitations_feature")]

    operations = [
        migrations.AddField(
            model_name="makerspace", name="event_reminder_lead_hours",
            field=models.JSONField(blank=True, default=default_reminder_lead_hours,
                                   validators=[validate_reminder_lead_hours]),
        ),
        migrations.AddField(
            model_name="makerspace", name="booking_reminder_lead_hours",
            field=models.JSONField(blank=True, default=default_reminder_lead_hours,
                                   validators=[validate_reminder_lead_hours]),
        ),
    ]
