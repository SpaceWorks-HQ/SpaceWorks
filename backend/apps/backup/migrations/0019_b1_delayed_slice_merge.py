from importlib import import_module

from django.db import migrations, models


GUARDS = r"""
CREATE OR REPLACE FUNCTION backup_b1_restore_component_guard() RETURNS trigger AS $$
DECLARE
  operation_record backup_b1restoreoperationstate%ROWTYPE;
  old_rank integer;
  new_rank integer;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'restore component state cannot be deleted';
  END IF;
  IF TG_OP = 'INSERT' THEN
    SELECT * INTO STRICT operation_record FROM backup_b1restoreoperationstate
     WHERE operation_id = NEW.operation_id;
    IF operation_record.artifact_id <> NEW.artifact_id
       OR operation_record.capture_id <> NEW.capture_id THEN
      RAISE EXCEPTION 'restore component binding does not match its operation';
    END IF;
    IF NEW.state <> 'pending' OR NEW.dependency_facts <> '[]'::jsonb
       OR NEW.merge_checkpoint <> '' THEN
      RAISE EXCEPTION 'restore component must begin pending and empty';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.operation_id <> NEW.operation_id OR OLD.artifact_id <> NEW.artifact_id
     OR OLD.capture_id <> NEW.capture_id OR OLD.component_id <> NEW.component_id
     OR OLD.makerspace_id_snapshot <> NEW.makerspace_id_snapshot
     OR OLD.ciphertext_sha256 <> NEW.ciphertext_sha256
     OR OLD.created_at <> NEW.created_at THEN
    RAISE EXCEPTION 'restore component identity is immutable';
  END IF;
  IF jsonb_typeof(NEW.dependency_facts) <> 'array'
     OR (OLD.dependency_facts <> '[]'::jsonb
         AND OLD.dependency_facts <> NEW.dependency_facts) THEN
    RAISE EXCEPTION 'authenticated dependency facts are immutable once recorded';
  END IF;
  old_rank := COALESCE(array_position(ARRAY[
    'staged', 'keys_installed', 'rows_applied', 'objects_promoted', 'verified'
  ], NULLIF(OLD.merge_checkpoint, '')), 0);
  new_rank := COALESCE(array_position(ARRAY[
    'staged', 'keys_installed', 'rows_applied', 'objects_promoted', 'verified'
  ], NULLIF(NEW.merge_checkpoint, '')), 0);
  IF NOT (
    (NEW.state = 'dependency_wait' AND NEW.merge_checkpoint = '' AND old_rank <= 2)
    OR (NEW.state = 'failed' AND new_rank = old_rank)
    OR (new_rank >= old_rank AND new_rank <= old_rank + 1
        AND (new_rank = 0 OR NEW.state IN ('merging', 'restored')))
  ) THEN
    RAISE EXCEPTION 'slice merge checkpoints must advance exactly once while merging';
  END IF;
  IF OLD.state = NEW.state THEN RETURN NEW; END IF;
  IF NOT (CASE OLD.state
    WHEN 'pending' THEN NEW.state IN ('dependency_wait', 'merging', 'failed')
    WHEN 'dependency_wait' THEN NEW.state IN ('pending', 'merging', 'failed')
    WHEN 'merging' THEN NEW.state IN ('dependency_wait', 'restored', 'failed')
    ELSE false
  END) THEN
    RAISE EXCEPTION 'invalid restore component state transition: % -> %', OLD.state, NEW.state;
  END IF;
  IF NEW.state = 'restored' AND NEW.merge_checkpoint <> 'verified' THEN
    RAISE EXCEPTION 'a slice cannot become restored before final verification';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE OR REPLACE FUNCTION backup_b1_reservation_state_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_setting('app.b1_merge_operation', true) IS NULL OR NOT EXISTS (
      SELECT 1 FROM backup_b1restorecomponentstate component
       WHERE component.operation_id = OLD.operation_id
         AND component.component_id = OLD.component_id
         AND component.state = 'restored'
         AND component.operation_id::text = current_setting('app.b1_merge_operation', true)
    ) THEN
      RAISE EXCEPTION 'restore reservations may clear only after a verified final merge';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.operation_id <> NEW.operation_id OR OLD.component_id <> NEW.component_id
     OR OLD.registry_identity <> NEW.registry_identity OR OLD.kind <> NEW.kind
     OR OLD.definition_sha256 <> NEW.definition_sha256 OR OLD.safe_payload <> NEW.safe_payload
     OR OLD.installed_at IS NOT NULL AND OLD.installed_at IS DISTINCT FROM NEW.installed_at
     OR OLD.catalog_verified_at IS NOT NULL
        AND OLD.catalog_verified_at IS DISTINCT FROM NEW.catalog_verified_at THEN
    RAISE EXCEPTION 'restore reservation facts are immutable';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE OR REPLACE FUNCTION backup_b1_merge_owns_component(reserved_component uuid)
RETURNS boolean AS $$
  SELECT current_user = 'spaceworks_b1_merge'
     AND reserved_component::text = current_setting('app.b1_merge_component', true)
     AND EXISTS (
       SELECT 1 FROM public.backup_b1restorecomponentstate component
        WHERE component.operation_id::text = current_setting('app.b1_merge_operation', true)
          AND component.component_id = reserved_component
          AND component.state = 'merging'
     );
$$ LANGUAGE sql STABLE SET search_path = pg_catalog, public;

CREATE OR REPLACE FUNCTION backup_b1_reject_pending_makerspace_materialization()
RETURNS trigger AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM public.backup_b1restorecomponentstate component
     WHERE component.makerspace_id_snapshot = NEW.id AND component.state <> 'restored'
       AND NOT backup_b1_merge_owns_component(component.component_id)
  ) THEN
    RAISE EXCEPTION 'makerspace is persistently not restored';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE OR REPLACE FUNCTION backup_b1_enforce_reservations() RETURNS trigger AS $$
DECLARE
  reservation record;
  payload jsonb;
  old_row jsonb := CASE WHEN TG_OP = 'INSERT' THEN '{}'::jsonb ELSE to_jsonb(OLD) END;
  new_row jsonb := CASE WHEN TG_OP = 'DELETE' THEN '{}'::jsonb ELSE to_jsonb(NEW) END;
  operation_name text := lower(TG_OP);
  column_name text;
  numeric_value numeric;
  relevant boolean;
BEGIN
  FOR reservation IN
    SELECT entry.*, component.makerspace_id_snapshot
      FROM public.backup_b1reservationentry entry
      JOIN public.backup_b1restorecomponentstate component
        ON component.operation_id = entry.operation_id
       AND component.component_id = entry.component_id
     WHERE component.state <> 'restored' AND entry.installed_at IS NOT NULL
       AND NOT backup_b1_merge_owns_component(entry.component_id)
       AND COALESCE(entry.safe_payload->>'schema',
                    entry.safe_payload->'enforcement'->>'schema', 'public') = TG_TABLE_SCHEMA
       AND COALESCE(entry.safe_payload->>'table',
                    entry.safe_payload->'enforcement'->>'table') = TG_TABLE_NAME
  LOOP
    payload := reservation.safe_payload;
    IF reservation.kind = 'numeric_range' AND TG_OP IN ('INSERT', 'UPDATE') THEN
      column_name := payload->>'column';
      IF new_row->>column_name IS NOT NULL THEN
        numeric_value := (new_row->>column_name)::numeric;
        IF numeric_value BETWEEN (payload->>'lower_inclusive')::numeric
                             AND (payload->>'upper_inclusive')::numeric THEN
          RAISE EXCEPTION 'write claims a reserved numeric identity';
        END IF;
      END IF;
    ELSIF reservation.kind = 'commitment' AND TG_OP IN ('INSERT', 'UPDATE') THEN
      IF backup_b1_commitment_matches(payload, reservation.component_id, new_row) THEN
        RAISE EXCEPTION 'write claims a reserved unique value';
      END IF;
    ELSIF reservation.kind = 'broad_fence'
      AND (payload->'operations') ? operation_name THEN
      IF TG_OP <> 'UPDATE' OR backup_b1_columns_changed(payload, old_row, new_row) THEN
        RAISE EXCEPTION 'write is blocked by a low-entropy unique fence';
      END IF;
    ELSIF reservation.kind = 'relationship_fence'
      AND (payload->'operations') ? operation_name THEN
      relevant := TG_OP = 'DELETE';
      IF NOT relevant AND payload->>'dependency_kind' = 'boundary_inbound_fk' THEN
        FOR column_name IN SELECT jsonb_array_elements_text(payload->'columns') LOOP
          relevant := relevant OR new_row->>column_name = reservation.makerspace_id_snapshot::text;
        END LOOP;
      ELSIF NOT relevant AND payload->>'dependency_kind' = 'semantic_reference' THEN
        relevant := true;
      ELSIF NOT relevant AND TG_TABLE_NAME = 'makerspaces_makerspace' THEN
        relevant := new_row->>'id' = reservation.makerspace_id_snapshot::text;
      ELSIF NOT relevant THEN
        relevant := true;
      END IF;
      IF relevant THEN
        RAISE EXCEPTION 'write is blocked by an opaque relationship fence';
      END IF;
    ELSIF reservation.kind = 'object_namespace'
      AND (payload->'operations') ? operation_name THEN
      relevant := TG_OP = 'DELETE';
      FOR column_name IN SELECT jsonb_array_elements_text(payload->'columns') LOOP
        relevant := relevant OR (
          TG_OP = 'INSERT' AND COALESCE(new_row->>column_name, '') <> ''
        ) OR (
          TG_OP = 'UPDATE' AND old_row->column_name IS DISTINCT FROM new_row->column_name
        );
      END LOOP;
      IF relevant THEN
        RAISE EXCEPTION 'write is blocked by an opaque object namespace fence';
      END IF;
    END IF;
  END LOOP;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;
"""


def _prior_function(module_name, constant, function_name):
    source = getattr(import_module(module_name), constant)
    marker = f"CREATE FUNCTION {function_name}"
    start = source.index(marker)
    end = source.index("$$ LANGUAGE ", start)
    end = source.index(";", end) + 1
    return source[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


REVERSE_GUARDS = "\n".join((
    _prior_function(
        "apps.backup.migrations.0017_b1_restore_state_guards",
        "STATE_GUARDS", "backup_b1_restore_component_guard()",
    ),
    _prior_function(
        "apps.backup.migrations.0017_b1_restore_state_guards",
        "STATE_GUARDS", "backup_b1_reservation_state_guard()",
    ),
    _prior_function(
        "apps.backup.migrations.0017_b1_restore_state_guards",
        "STATE_GUARDS", "backup_b1_reject_pending_makerspace_materialization()",
    ),
    _prior_function(
        "apps.backup.migrations.0018_b1_reservation_enforcement",
        "ENFORCEMENT", "backup_b1_enforce_reservations()",
    ),
    "DROP FUNCTION IF EXISTS backup_b1_merge_owns_component(uuid);",
))


class Migration(migrations.Migration):
    dependencies = [("backup", "0018_b1_reservation_enforcement")]
    operations = [
        migrations.AddField(
            model_name="b1restorecomponentstate",
            name="dependency_facts",
            field=models.JSONField(blank=True, default=list, editable=False),
        ),
        migrations.AddField(
            model_name="b1restorecomponentstate",
            name="merge_checkpoint",
            field=models.CharField(
                blank=True,
                choices=[
                    ("staged", "Raw slice staged"),
                    ("keys_installed", "Target keys installed"),
                    ("rows_applied", "Rows applied"),
                    ("objects_promoted", "Objects promoted"),
                    ("verified", "Final verification complete"),
                ],
                max_length=24,
            ),
        ),
        migrations.RunSQL(GUARDS, REVERSE_GUARDS),
    ]
