import uuid

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


def _bootstrap_first_generation(apps, schema_editor):
    apps.get_model("audit", "AuditSigningKey").objects.all().update(
        version=1,
        is_active=True,
        valid_from_seq=0,
        valid_to_seq=None,
    )


SIGNING_KEY_GUARD_SQL = """
CREATE OR REPLACE FUNCTION audit_signing_key_lifecycle_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.makerspace_id IS DISTINCT FROM NEW.makerspace_id
       OR OLD.public_key IS DISTINCT FROM NEW.public_key
       OR OLD.fingerprint IS DISTINCT FROM NEW.fingerprint
       OR OLD.version IS DISTINCT FROM NEW.version
       OR OLD.valid_from_seq IS DISTINCT FROM NEW.valid_from_seq
       OR OLD.activation_payload IS DISTINCT FROM NEW.activation_payload
       OR OLD.activation_signature IS DISTINCT FROM NEW.activation_signature
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'immutable audit signing-key material cannot be changed';
    END IF;

    IF OLD.wrapped_private_key IS NULL AND NEW.wrapped_private_key IS NOT NULL THEN
        RAISE EXCEPTION 'a cleared audit signing private key cannot be restored';
    END IF;
    IF OLD.wrapped_private_key IS NOT NULL
       AND NEW.wrapped_private_key IS DISTINCT FROM OLD.wrapped_private_key
       AND NEW.wrapped_private_key IS NOT NULL THEN
        RAISE EXCEPTION 'wrapped audit signing private key cannot be replaced';
    END IF;

    IF OLD.activated_at IS NOT NULL
       AND NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
        RAISE EXCEPTION 'audit signing-key activation cannot be changed';
    END IF;
    IF OLD.valid_to_seq IS NOT NULL
       AND NEW.valid_to_seq IS DISTINCT FROM OLD.valid_to_seq THEN
        RAISE EXCEPTION 'audit signing-key validity cannot be reopened or changed';
    END IF;
    IF OLD.pending_rotation_id IS NOT NULL
       AND NEW.pending_rotation_id IS NOT NULL
       AND NEW.pending_rotation_id IS DISTINCT FROM OLD.pending_rotation_id THEN
        RAISE EXCEPTION 'pending audit signing-key rotation cannot be replaced';
    END IF;

    IF OLD.is_active = FALSE AND NEW.is_active = TRUE
       AND NOT (OLD.activated_at IS NULL AND NEW.activated_at IS NOT NULL) THEN
        RAISE EXCEPTION 'retired audit signing keys cannot be reactivated';
    END IF;
    IF OLD.is_active = TRUE AND NEW.is_active = FALSE
       AND NOT (
           OLD.valid_to_seq IS NULL AND NEW.valid_to_seq IS NOT NULL
           AND OLD.wrapped_private_key IS NOT NULL
           AND NEW.wrapped_private_key IS NULL
           AND NEW.pending_rotation_id IS NULL
       ) THEN
        RAISE EXCEPTION 'audit signing-key retirement must close its interval and clear its live key';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER audit_signing_key_lifecycle
BEFORE UPDATE ON audit_auditsigningkey
FOR EACH ROW EXECUTE FUNCTION audit_signing_key_lifecycle_guard();
"""


IMMUTABILITY_SQL = """
CREATE TRIGGER audit_signing_key_rotation_no_update
BEFORE UPDATE ON audit_auditsigningkeyrotation
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
CREATE TRIGGER audit_signing_key_rotation_no_delete
BEFORE DELETE ON audit_auditsigningkeyrotation
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
CREATE TRIGGER audit_signing_key_rotation_event_no_update
BEFORE UPDATE ON audit_auditsigningkeyrotationevent
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
CREATE TRIGGER audit_signing_key_rotation_event_no_delete
BEFORE DELETE ON audit_auditsigningkeyrotationevent
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0005_audit_batch_attestation")]

    operations = [
        migrations.RemoveConstraint(
            model_name="auditsigningkey",
            name="uniq_audit_signing_key_scope",
        ),
        migrations.AlterField(
            model_name="auditsigningkey",
            name="wrapped_private_key",
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="auditsigningkey",
            name="version",
            field=models.PositiveBigIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="auditsigningkey",
            name="valid_from_seq",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="auditsigningkey",
            name="valid_to_seq",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="auditsigningkey",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(
            _bootstrap_first_generation,
            migrations.RunPython.noop,
        ),
        migrations.CreateModel(
            name="AuditSigningKeyRotation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("old_fingerprint", models.CharField(max_length=64)),
                ("new_fingerprint", models.CharField(max_length=64)),
                ("old_version", models.PositiveBigIntegerField()),
                ("new_version", models.PositiveBigIntegerField()),
                ("last_old_batch_seq", models.PositiveBigIntegerField()),
                ("last_old_batch_root", models.BinaryField()),
                ("payload", models.JSONField()),
                ("old_signature", models.BinaryField()),
                ("new_signature", models.BinaryField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("makerspace", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="audit_signing_key_rotations", to="makerspaces.makerspace")),
                ("new_key", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="rotation_to", to="audit.auditsigningkey")),
                ("old_key", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="rotation_from", to="audit.auditsigningkey")),
            ],
            options={"ordering": ["makerspace_id", "old_version"]},
        ),
        migrations.CreateModel(
            name="AuditSigningKeyRotationEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("state", models.CharField(choices=[("PREPARED", "Prepared"), ("PUBLISHED", "Published"), ("FINALIZED", "Finalized"), ("ABORTED", "Aborted")], max_length=16)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("rotation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="audit.auditsigningkeyrotation")),
            ],
            options={"ordering": ["created_at", "pk"]},
        ),
        migrations.AddField(
            model_name="auditsigningkey",
            name="pending_rotation",
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="pending_on_key", to="audit.auditsigningkeyrotation"),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                """CREATE UNIQUE INDEX uniq_active_audit_signing_key_scope
ON audit_auditsigningkey (makerspace_id) NULLS NOT DISTINCT
WHERE is_active;""",
                "DROP INDEX IF EXISTS uniq_active_audit_signing_key_scope;",
            )],
            state_operations=[migrations.AddConstraint(
                model_name="auditsigningkey",
                constraint=models.UniqueConstraint(condition=models.Q(("is_active", True)), fields=("makerspace",), name="uniq_active_audit_signing_key_scope", nulls_distinct=False),
            )],
        ),
        migrations.AddConstraint(
            model_name="auditsigningkey",
            constraint=models.UniqueConstraint(fields=("makerspace", "version"), name="uniq_audit_signing_key_scope_version", nulls_distinct=False),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                """CREATE UNIQUE INDEX uniq_audit_pending_rotation_scope
ON audit_auditsigningkey (makerspace_id) NULLS NOT DISTINCT
WHERE pending_rotation_id IS NOT NULL;""",
                "DROP INDEX IF EXISTS uniq_audit_pending_rotation_scope;",
            )],
            state_operations=[migrations.AddConstraint(
                model_name="auditsigningkey",
                constraint=models.UniqueConstraint(condition=models.Q(("pending_rotation__isnull", False)), fields=("makerspace",), name="uniq_audit_pending_rotation_scope", nulls_distinct=False),
            )],
        ),
        migrations.AddConstraint(
            model_name="auditsigningkey",
            constraint=models.CheckConstraint(condition=models.Q(("valid_to_seq__isnull", True), ("valid_to_seq__gte", models.F("valid_from_seq")), _connector="OR"), name="ck_audit_signing_key_valid_interval"),
        ),
        migrations.AddConstraint(
            model_name="auditsigningkey",
            constraint=models.CheckConstraint(condition=models.Q(("pending_rotation__isnull", True), ("is_active", True), _connector="OR"), name="ck_audit_pending_rotation_on_active_key"),
        ),
        migrations.AddConstraint(
            model_name="auditsigningkey",
            constraint=models.CheckConstraint(condition=models.Q(("is_active", False), models.Q(("valid_to_seq__isnull", True), ("wrapped_private_key__isnull", False)), _connector="OR"), name="ck_active_audit_signing_key_open"),
        ),
        migrations.AddConstraint(
            model_name="auditsigningkeyrotation",
            constraint=_octet_constraint("last_old_batch_root", 32, "ck_audit_rotation_head_root_32_bytes"),
        ),
        migrations.AddConstraint(
            model_name="auditsigningkeyrotation",
            constraint=_octet_constraint("old_signature", 64, "ck_audit_rotation_old_signature_64_bytes"),
        ),
        migrations.AddConstraint(
            model_name="auditsigningkeyrotation",
            constraint=_octet_constraint("new_signature", 64, "ck_audit_rotation_new_signature_64_bytes"),
        ),
        migrations.AddConstraint(
            model_name="auditsigningkeyrotation",
            constraint=models.CheckConstraint(condition=models.Q(("new_version", models.F("old_version") + 1)), name="ck_audit_rotation_adjacent_versions"),
        ),
        migrations.AddConstraint(
            model_name="auditsigningkeyrotationevent",
            constraint=models.UniqueConstraint(fields=("rotation", "state"), name="uniq_audit_rotation_event_state"),
        ),
        migrations.RunSQL(
            SIGNING_KEY_GUARD_SQL,
            "DROP TRIGGER IF EXISTS audit_signing_key_lifecycle ON audit_auditsigningkey; DROP FUNCTION IF EXISTS audit_signing_key_lifecycle_guard();",
        ),
        migrations.RunSQL(
            IMMUTABILITY_SQL,
            """
DROP TRIGGER IF EXISTS audit_signing_key_rotation_event_no_delete ON audit_auditsigningkeyrotationevent;
DROP TRIGGER IF EXISTS audit_signing_key_rotation_event_no_update ON audit_auditsigningkeyrotationevent;
DROP TRIGGER IF EXISTS audit_signing_key_rotation_no_delete ON audit_auditsigningkeyrotation;
DROP TRIGGER IF EXISTS audit_signing_key_rotation_no_update ON audit_auditsigningkeyrotation;
""",
        ),
    ]
