import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0005_evidenceuploadfinalization"),
        ("makerspaces", "0067_reconcile_anonymous_requests_with_membership"),
    ]

    operations = [
        migrations.CreateModel(
            name="EvidenceRetentionPolicy",
            fields=[
                (
                    "makerspace",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="evidence_retention_policy",
                        serialize=False,
                        to="makerspaces.makerspace",
                    ),
                ),
                (
                    "object_retention_days",
                    models.PositiveIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(30),
                            django.core.validators.MaxValueValidator(3650),
                        ]
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="EvidenceObjectRetentionState",
            fields=[
                (
                    "evidence",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="object_retention_state",
                        serialize=False,
                        to="evidence.evidencephoto",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("expiring", "Expiring"), ("expired", "Expired")],
                        default="expiring",
                        max_length=16,
                    ),
                ),
                ("claim_token", models.UUIDField(blank=True, null=True)),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("object_expired_at", models.DateTimeField(blank=True, null=True)),
                ("expired_size_bytes", models.PositiveBigIntegerField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="evidenceretentionpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("object_retention_days__gte", 30),
                    ("object_retention_days__lte", 3650),
                ),
                name="ck_evidence_retention_days_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="evidenceobjectretentionstate",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        ("claim_token__isnull", True),
                        ("claimed_at__isnull", True),
                        ("object_expired_at__isnull", False),
                        ("status", "expired"),
                    )
                    | models.Q(
                        ("object_expired_at__isnull", True),
                        ("status", "expiring"),
                    )
                ),
                name="ck_evidence_retention_terminal_state",
            ),
        ),
    ]
