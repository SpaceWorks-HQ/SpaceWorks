from django.db import migrations, models
import django.db.models.deletion
import apps.operations.models_rollups


APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION operations_report_rollup_reject_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('app.allow_immutable_delete', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'append-only report metric rollup: % not allowed', TG_OP;
END;
$$;
CREATE TRIGGER operations_report_rollup_no_update
BEFORE UPDATE ON operations_reportmetricrollup
FOR EACH ROW EXECUTE FUNCTION operations_report_rollup_reject_mutation();
CREATE TRIGGER operations_report_rollup_no_delete
BEFORE DELETE ON operations_reportmetricrollup
FOR EACH ROW EXECUTE FUNCTION operations_report_rollup_reject_mutation();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS operations_report_rollup_no_update ON operations_reportmetricrollup;
DROP TRIGGER IF EXISTS operations_report_rollup_no_delete ON operations_reportmetricrollup;
DROP FUNCTION IF EXISTS operations_report_rollup_reject_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0007_spaceworks_cache")]

    operations = [
        migrations.CreateModel(
            name="ReportRollupCursor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_module", models.CharField(max_length=64)),
                ("rolled_through", models.DateTimeField(blank=True, null=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_code", models.CharField(blank=True, default="", max_length=64)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="report_rollup_cursors", to="makerspaces.makerspace")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("makerspace", "source_module"), name="uniq_report_rollup_cursor")]},
        ),
        migrations.CreateModel(
            name="ReportMetricRollup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_module", models.CharField(max_length=64)),
                ("report_key", models.CharField(max_length=80)),
                ("metric_key", models.CharField(max_length=80)),
                ("bucket_start", models.DateTimeField()),
                ("grain", models.CharField(choices=[("day", "Day"), ("month", "Month")], max_length=8)),
                ("dimension_key", models.CharField(max_length=128)),
                ("dimensions", models.JSONField(default=dict, validators=[apps.operations.models_rollups.validate_rollup_dimensions])),
                ("value", models.DecimalField(decimal_places=6, max_digits=28)),
                ("sample_count", models.PositiveBigIntegerField(default=0)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("source_cutoff", models.DateTimeField()),
                ("computed_at", models.DateTimeField(auto_now_add=True)),
                ("checksum", models.CharField(max_length=64)),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="report_metric_rollups", to="makerspaces.makerspace")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["makerspace", "report_key", "bucket_start"], name="report_rollup_space_report_idx"),
                    models.Index(fields=["source_module", "bucket_start"], name="report_rollup_source_bucket_idx"),
                ],
                "constraints": [models.UniqueConstraint(fields=("makerspace", "report_key", "metric_key", "bucket_start", "grain", "dimension_key", "revision"), name="uniq_report_metric_rollup_revision")],
            },
        ),
        migrations.RunSQL(APPEND_ONLY_SQL, REVERSE_SQL),
    ]
