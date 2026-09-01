from django.db import migrations, models


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION pii_assert_mapped_write_allowed(p_makerspace_id bigint)
RETURNS void AS $$
DECLARE global_fence record; tenant_fence record; operation text;
BEGIN
  PERFORM pg_advisory_xact_lock_shared(734201, 0);
  IF p_makerspace_id IS NOT NULL THEN
    PERFORM pg_advisory_xact_lock_shared(734202, p_makerspace_id::integer);
  END IF;
  SELECT state, operation_id, operation_kind INTO global_fence
    FROM encryption_piiglobalwritefence WHERE id = 1;
  IF NOT FOUND THEN RAISE EXCEPTION 'pii write fence missing'; END IF;
  operation := current_setting('app.pii_fence_operation', true);
  IF global_fence.state = 'closed' AND (
    operation IS DISTINCT FROM global_fence.operation_id::text OR
    global_fence.operation_kind NOT IN (
      'enable_transition', 'decrypt_rollback', 'search_rotation', 'tenant_import'
    )
  ) THEN RAISE EXCEPTION 'pii write fence closed'; END IF;
  IF p_makerspace_id IS NOT NULL THEN
    SELECT state, operation_id, operation_kind INTO tenant_fence
      FROM encryption_piimakerspacewritefence WHERE makerspace_id = p_makerspace_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'pii write fence missing'; END IF;
    IF tenant_fence.state = 'closed' AND (
      operation IS DISTINCT FROM tenant_fence.operation_id::text OR
      tenant_fence.operation_kind NOT IN (
        'enable_transition', 'decrypt_rollback', 'search_rotation', 'tenant_import'
      )
    ) THEN RAISE EXCEPTION 'pii write fence closed'; END IF;
  END IF;
END;
$$ LANGUAGE plpgsql;
"""

REVERSE_SQL = FORWARD_SQL.replace(", 'tenant_import'", "")


class Migration(migrations.Migration):
    dependencies = [("encryption", "0006_machine_service_request_pii_fence")]

    operations = [
        migrations.AlterField(
            model_name="piiglobalwritefence",
            name="operation_kind",
            field=models.CharField(
                blank=True,
                choices=[
                    ("enable_transition", "Enable transition"),
                    ("decrypt_rollback", "Decrypt rollback"),
                    ("search_rotation", "Search rotation"),
                    ("tenant_import", "Tenant import"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="piimakerspacewritefence",
            name="operation_kind",
            field=models.CharField(
                blank=True,
                choices=[
                    ("enable_transition", "Enable transition"),
                    ("decrypt_rollback", "Decrypt rollback"),
                    ("search_rotation", "Search rotation"),
                    ("tenant_import", "Tenant import"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
