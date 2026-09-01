import django.db.models.deletion
import django.db.models.lookups
import django.utils.timezone
from django.db import migrations, models


def _octet_constraint(field_name, length, name):
    return models.CheckConstraint(
        condition=django.db.models.lookups.Exact(
            models.Func(
                models.F(field_name),
                function="OCTET_LENGTH",
                output_field=models.IntegerField(),
            ),
            length,
        ),
        name=name,
    )


class Migration(migrations.Migration):
    dependencies = [("audit", "0004_audit_mac_integrity")]

    operations = [
        migrations.CreateModel(
            name="AuditSigningKey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("wrapped_private_key", models.BinaryField()),
                ("public_key", models.BinaryField()),
                ("fingerprint", models.CharField(max_length=64)),
                ("activation_payload", models.JSONField(default=dict)),
                ("activation_signature", models.BinaryField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("makerspace", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="audit_signing_keys", to="makerspaces.makerspace")),
            ],
        ),
        migrations.CreateModel(
            name="AuditBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("batch_seq", models.PositiveBigIntegerField()),
                ("leaf_count", models.PositiveIntegerField()),
                ("merkle_root", models.BinaryField()),
                ("prev_batch_root", models.BinaryField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("signature", models.BinaryField()),
                ("signer_fingerprint", models.CharField(max_length=64)),
                ("makerspace", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="audit_batches", to="makerspaces.makerspace")),
            ],
            options={"ordering": ["makerspace_id", "batch_seq"]},
        ),
        migrations.CreateModel(
            name="AuditBatchLeaf",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("leaf_position", models.PositiveIntegerField()),
                ("audit_log", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="batch_leaf", to="audit.auditlog")),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="leaves", to="audit.auditbatch")),
            ],
            options={"ordering": ["leaf_position"]},
        ),
        migrations.AddConstraint(
            model_name="auditsigningkey",
            constraint=models.UniqueConstraint(fields=("makerspace",), name="uniq_audit_signing_key_scope", nulls_distinct=False),
        ),
        migrations.AddConstraint(
            model_name="auditsigningkey",
            constraint=_octet_constraint("public_key", 32, "ck_audit_signing_public_key_32_bytes"),
        ),
        migrations.AddConstraint(
            model_name="auditsigningkey",
            constraint=_octet_constraint("activation_signature", 64, "ck_audit_activation_signature_64_bytes"),
        ),
        migrations.AddConstraint(
            model_name="auditbatch",
            constraint=models.UniqueConstraint(fields=("makerspace", "batch_seq"), name="uniq_audit_batch_scope_seq", nulls_distinct=False),
        ),
        migrations.AddConstraint(
            model_name="auditbatch",
            constraint=models.CheckConstraint(condition=models.Q(("leaf_count__gt", 0)), name="ck_audit_batch_leaf_count_positive"),
        ),
        migrations.AddConstraint(
            model_name="auditbatch",
            constraint=_octet_constraint("merkle_root", 32, "ck_audit_batch_merkle_root_32_bytes"),
        ),
        migrations.AddConstraint(
            model_name="auditbatch",
            constraint=_octet_constraint("prev_batch_root", 32, "ck_audit_batch_prev_root_32_bytes"),
        ),
        migrations.AddConstraint(
            model_name="auditbatch",
            constraint=_octet_constraint("signature", 64, "ck_audit_batch_signature_64_bytes"),
        ),
        migrations.AddConstraint(
            model_name="auditbatchleaf",
            constraint=models.UniqueConstraint(fields=("batch", "leaf_position"), name="uniq_audit_batch_leaf_position"),
        ),
        migrations.RunSQL(
            sql="""
CREATE TRIGGER audit_batch_no_update
BEFORE UPDATE ON audit_auditbatch
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
CREATE TRIGGER audit_batch_no_delete
BEFORE DELETE ON audit_auditbatch
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
CREATE TRIGGER audit_batch_leaf_no_update
BEFORE UPDATE ON audit_auditbatchleaf
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
CREATE TRIGGER audit_batch_leaf_no_delete
BEFORE DELETE ON audit_auditbatchleaf
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
""",
            reverse_sql="""
DROP TRIGGER IF EXISTS audit_batch_leaf_no_delete ON audit_auditbatchleaf;
DROP TRIGGER IF EXISTS audit_batch_leaf_no_update ON audit_auditbatchleaf;
DROP TRIGGER IF EXISTS audit_batch_no_delete ON audit_auditbatch;
DROP TRIGGER IF EXISTS audit_batch_no_update ON audit_auditbatch;
""",
        ),
    ]
