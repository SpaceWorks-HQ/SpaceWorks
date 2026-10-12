from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("operations", "0009_report_schedules")]

    operations = [
        migrations.CreateModel(
            name="ReminderSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("source", models.CharField(max_length=80)),
                ("subject", models.CharField(max_length=160)),
                ("kind", models.CharField(max_length=80)),
                ("offset_seconds", models.IntegerField()),
                ("due_at", models.DateTimeField()),
                ("remind_at", models.DateTimeField()),
                ("state", models.CharField(default="pending", max_length=16, choices=[
                    ("pending", "Pending"), ("claimed", "Claimed"),
                    ("completed", "Completed"), ("failed", "Failed"),
                ])),
                ("claim_token", models.UUIDField(blank=True, null=True)),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("makerspace", models.ForeignKey(
                    to="makerspaces.makerspace", on_delete=django.db.models.deletion.CASCADE,
                    related_name="reminder_schedules",
                )),
            ],
            options={
                "indexes": [models.Index(
                    fields=["makerspace", "source", "state", "remind_at"],
                    name="reminder_ms_source_due_idx",
                )],
                "constraints": [
                    models.UniqueConstraint(
                        fields=["makerspace", "source", "subject", "kind", "offset_seconds"],
                        name="uniq_reminder_subject_kind_step",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(state="pending", claim_token__isnull=True,
                                     claimed_at__isnull=True, completed_at__isnull=True)
                            | models.Q(state="claimed", claim_token__isnull=False,
                                       claimed_at__isnull=False, completed_at__isnull=True)
                            | models.Q(state__in=["completed", "failed"], claim_token__isnull=False,
                                       claimed_at__isnull=False, completed_at__isnull=False)
                        ),
                        name="reminder_claim_state_consistent",
                    ),
                ],
            },
        ),
    ]
