import uuid

import apps.forms_schema.validation
from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0017_event_feedback_certificates"),
        ("organizations", "0002_organizationmembership"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EventSeries",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_token", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("location", models.CharField(blank=True, max_length=255)),
                ("location_kind", models.CharField(choices=[("indoor", "Indoor"), ("outdoor", "Outdoor"), ("other", "Other")], default="other", max_length=8)),
                ("custom_form", models.JSONField(blank=True, default=None, null=True, validators=[apps.forms_schema.validation.validate_form_schema])),
                ("capacity", models.PositiveIntegerField(default=0)),
                ("payment_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12, validators=[django.core.validators.MinValueValidator(0)])),
                ("registration_requires_approval", models.BooleanField(default=False)),
                ("registration_cutoff_lead_minutes", models.PositiveIntegerField(blank=True, null=True)),
                ("is_public", models.BooleanField(default=False)),
                ("image_key", models.CharField(blank=True, default="", max_length=300)),
                ("recurrence_timezone", models.CharField(max_length=64)),
                ("dtstart_local_date", models.DateField()),
                ("dtstart_local_time", models.TimeField()),
                ("recurrence_rule", models.CharField(max_length=500)),
                ("duration_minutes", models.PositiveIntegerField()),
                ("revision", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("published", "Published"), ("cancelled", "Cancelled"), ("completed", "Completed")], default="draft", max_length=16)),
                ("last_materialized_at", models.DateTimeField(blank=True, null=True)),
                ("last_generation_error_code", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="event_series", to="makerspaces.makerspace")),
            ],
            options={"ordering": ("dtstart_local_date", "dtstart_local_time", "id")},
        ),
        migrations.CreateModel(
            name="EventSeriesCollaborator",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("invited", "Invited"), ("accepted", "Accepted"), ("declined", "Declined")], default="invited", max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("invited_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="event_series_collaborations", to="makerspaces.makerspace")),
                ("responded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("series", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="collaborators", to="events.eventseries")),
            ],
        ),
        migrations.CreateModel(
            name="EventSeriesOrganizer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="organized_event_series", to="organizations.organization")),
                ("series", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="organizers", to="events.eventseries")),
            ],
        ),
        migrations.AddField(model_name="event", name="series", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="occurrences", to="events.eventseries")),
        migrations.AddField(model_name="event", name="series_occurrence_key", field=models.CharField(blank=True, max_length=48, null=True)),
        migrations.AddField(model_name="event", name="series_override_fields", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="event", name="series_revision", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="eventcollaborator", name="source_series_collaboration", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="occurrence_collaborators", to="events.eventseriescollaborator")),
        migrations.AddField(model_name="eventorganizer", name="source_series_organizer", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="occurrence_organizers", to="events.eventseriesorganizer")),
        migrations.AddConstraint(model_name="eventseries", constraint=models.CheckConstraint(condition=models.Q(("capacity__gte", 0)), name="series_capacity_nonnegative")),
        migrations.AddConstraint(model_name="eventseries", constraint=models.CheckConstraint(condition=models.Q(("payment_amount__gte", 0)), name="series_payment_nonnegative")),
        migrations.AddConstraint(model_name="eventseries", constraint=models.CheckConstraint(condition=models.Q(("duration_minutes__gt", 0)), name="series_duration_positive")),
        migrations.AddConstraint(model_name="eventseries", constraint=models.CheckConstraint(condition=models.Q(("revision__gt", 0)), name="series_revision_positive")),
        migrations.AddIndex(model_name="eventseries", index=models.Index(fields=["makerspace", "status", "dtstart_local_date"], name="series_ms_status_date_idx")),
        migrations.AddConstraint(model_name="eventseriescollaborator", constraint=models.UniqueConstraint(fields=("series", "makerspace"), name="uniq_series_collaborator_space")),
        migrations.AddConstraint(model_name="eventseriesorganizer", constraint=models.UniqueConstraint(fields=("series", "organization"), name="uniq_series_organizer_organization")),
        migrations.AddConstraint(
            model_name="event",
            constraint=models.CheckConstraint(
                condition=models.Q(("series__isnull", True), ("series_occurrence_key__isnull", True), ("series_revision__isnull", True))
                | models.Q(("series__isnull", False), ("series_occurrence_key__isnull", False), ("series_revision__isnull", False)),
                name="event_series_identity_all_or_none",
            ),
        ),
        migrations.AddConstraint(model_name="event", constraint=models.UniqueConstraint(fields=("series", "series_occurrence_key"), name="uniq_event_series_occurrence_key")),
        migrations.AddIndex(model_name="event", index=models.Index(fields=["series", "starts_at"], name="event_series_start_idx")),
    ]
