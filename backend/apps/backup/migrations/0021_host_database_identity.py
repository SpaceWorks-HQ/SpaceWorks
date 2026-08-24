import uuid

from django.db import migrations, models


IDENTITY_GUARD_SQL = """
CREATE OR REPLACE FUNCTION backup_guard_database_identity_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND current_setting('app.allow_immutable_delete', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'deployment database identity is immutable: % not allowed', TG_OP;
END;
$$;
CREATE TRIGGER backup_database_identity_no_update
BEFORE UPDATE ON backup_deploymentdatabaseidentity
FOR EACH ROW EXECUTE FUNCTION backup_guard_database_identity_mutation();
CREATE TRIGGER backup_database_identity_no_delete
BEFORE DELETE ON backup_deploymentdatabaseidentity
FOR EACH ROW EXECUTE FUNCTION backup_guard_database_identity_mutation();
"""

IDENTITY_GUARD_REVERSE_SQL = """
DROP TRIGGER IF EXISTS backup_database_identity_no_delete
ON backup_deploymentdatabaseidentity;
DROP TRIGGER IF EXISTS backup_database_identity_no_update
ON backup_deploymentdatabaseidentity;
DROP FUNCTION IF EXISTS backup_guard_database_identity_mutation();
"""


def seed_active_identity(apps, schema_editor):
    Identity = apps.get_model("backup", "DeploymentDatabaseIdentity")
    Identity.objects.get_or_create(pk=1, defaults={"database_uuid": uuid.uuid4()})


class Migration(migrations.Migration):
    dependencies = [("backup", "0015_tenant_exit_custody")]

    operations = [
        migrations.CreateModel(
            name="DeploymentDatabaseIdentity",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "database_uuid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("run_id", models.UUIDField(blank=True, null=True)),
                ("artifact_sha256", models.CharField(blank=True, max_length=64)),
                ("capture_id", models.UUIDField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(pk=1),
                        name="backup_database_identity_singleton_pk",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                run_id__isnull=True,
                                artifact_sha256="",
                                capture_id__isnull=True,
                            )
                            | models.Q(
                                run_id__isnull=False,
                                artifact_sha256__regex=r"^[0-9a-f]{64}$",
                                capture_id__isnull=False,
                            )
                        ),
                        name="backup_database_identity_lineage_complete",
                    )
                ]
            },
        ),
        migrations.RunPython(seed_active_identity, migrations.RunPython.noop),
        migrations.RunSQL(IDENTITY_GUARD_SQL, IDENTITY_GUARD_REVERSE_SQL),
    ]
