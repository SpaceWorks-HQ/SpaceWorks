from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


IMMUTABLE_SQL = """
CREATE OR REPLACE FUNCTION events_reject_checkin_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('app.allow_immutable_delete', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'append-only/immutable table: % not allowed', TG_OP;
END;
$$;
CREATE TRIGGER events_checkin_immutable
BEFORE UPDATE OR DELETE ON events_eventcheckinevent
FOR EACH ROW EXECUTE FUNCTION events_reject_checkin_mutation();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS events_checkin_immutable ON events_eventcheckinevent;
DROP FUNCTION IF EXISTS events_reject_checkin_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0015_event_registration_approval"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EventCheckInEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(choices=[("staff", "Staff confirmation"), ("qr", "QR check-in")], max_length=16)),
                ("attended_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("recorded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("registration", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="check_in_events", to="events.eventregistration")),
            ],
            options={
                "ordering": ["attended_at", "id"],
                "indexes": [models.Index(fields=["registration", "attended_at"], name="event_checkin_history_idx")],
            },
        ),
        migrations.RunSQL(IMMUTABLE_SQL, REVERSE_SQL),
    ]
