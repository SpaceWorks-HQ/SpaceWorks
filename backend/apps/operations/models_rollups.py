from django.core.exceptions import ValidationError
from django.db import models


ALLOWED_DIMENSION_KEYS = frozenset({
    "channel", "evidence_type", "feature", "kind", "mode", "module_key",
    "outcome", "source", "status", "subject_type", "currency",
})


def validate_rollup_dimensions(value):
    if not isinstance(value, dict):
        raise ValidationError("Rollup dimensions must be an object.")
    unknown = set(value) - ALLOWED_DIMENSION_KEYS
    if unknown:
        raise ValidationError(f"Unsupported rollup dimension keys: {sorted(unknown)}.")
    for key, item in value.items():
        if isinstance(item, (dict, list)):
            raise ValidationError(f"Rollup dimension {key!r} must be scalar.")
        if isinstance(item, str) and len(item) > 64:
            raise ValidationError(f"Rollup dimension {key!r} is too long.")


class ReportMetricRollup(models.Model):
    class Grain(models.TextChoices):
        DAY = "day", "Day"
        MONTH = "month", "Month"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="report_metric_rollups"
    )
    source_module = models.CharField(max_length=64)
    report_key = models.CharField(max_length=80)
    metric_key = models.CharField(max_length=80)
    bucket_start = models.DateTimeField()
    grain = models.CharField(max_length=8, choices=Grain.choices)
    dimension_key = models.CharField(max_length=128)
    dimensions = models.JSONField(default=dict, validators=[validate_rollup_dimensions])
    value = models.DecimalField(max_digits=28, decimal_places=6)
    sample_count = models.PositiveBigIntegerField(default=0)
    revision = models.PositiveIntegerField(default=1)
    source_cutoff = models.DateTimeField()
    computed_at = models.DateTimeField(auto_now_add=True)
    checksum = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("makerspace", "report_key", "metric_key", "bucket_start", "grain", "dimension_key", "revision"),
                name="uniq_report_metric_rollup_revision",
            ),
        ]
        indexes = [
            models.Index(fields=("makerspace", "report_key", "bucket_start"), name="report_rollup_space_report_idx"),
            models.Index(fields=("source_module", "bucket_start"), name="report_rollup_source_bucket_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("ReportMetricRollup rows are append-only.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("ReportMetricRollup rows are append-only.")


class ReportRollupCursor(models.Model):
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="report_rollup_cursors"
    )
    source_module = models.CharField(max_length=64)
    rolled_through = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("makerspace", "source_module"), name="uniq_report_rollup_cursor"
            ),
        ]
