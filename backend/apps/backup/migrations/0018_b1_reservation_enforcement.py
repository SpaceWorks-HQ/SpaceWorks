from django.db import migrations


ENFORCEMENT = r"""
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE FUNCTION backup_b1_frame(value bytea) RETURNS bytea AS $$
  SELECT pg_catalog.int8send(pg_catalog.octet_length(value)::bigint) || value;
$$ LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE;

CREATE FUNCTION backup_b1_columns_changed(
  payload jsonb, old_row jsonb, new_row jsonb
) RETURNS boolean AS $$
DECLARE
  column_name text;
BEGIN
  FOR column_name IN SELECT jsonb_array_elements_text(payload->'columns') LOOP
    IF column_name = '' OR old_row->column_name IS DISTINCT FROM new_row->column_name THEN
      RETURN true;
    END IF;
  END LOOP;
  RETURN false;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE FUNCTION backup_b1_commitment_matches(
  payload jsonb, reserved_component uuid, row_value jsonb
) RETURNS boolean AS $$
DECLARE
  enforcement jsonb := payload->'enforcement';
  component jsonb;
  component_value bytea;
  framed bytea;
  group_value jsonb;
  predicate_matches boolean;
BEGIN
  IF enforcement IS NULL
     OR payload->>'reservation_salt' IS NULL
     OR jsonb_typeof(enforcement->'components') <> 'array' THEN
    RAISE EXCEPTION 'commitment reservation lacks catalog-verified enforcement facts';
  END IF;
  EXECUTE format(
    'SELECT ((%s) IS TRUE) FROM jsonb_populate_record(NULL::%I.%I, $1) AS b1_row',
    COALESCE(NULLIF(enforcement->>'predicate_sql', ''), 'TRUE'),
    enforcement->>'schema', enforcement->>'table'
  ) INTO predicate_matches USING row_value;
  IF NOT predicate_matches THEN
    RETURN false;
  END IF;
  framed := backup_b1_frame(convert_to('reservation-key-v1', 'UTF8'))
    || backup_b1_frame(decode(payload->>'constraint_identity', 'hex'))
    || pg_catalog.int4send(jsonb_array_length(enforcement->'components'));
  FOR component IN SELECT * FROM jsonb_array_elements(enforcement->'components') LOOP
    EXECUTE format(
      'SELECT %s FROM jsonb_populate_record(NULL::%I.%I, $1) AS b1_row',
      component->>'canonicalizer_sql', enforcement->>'schema', enforcement->>'table'
    ) INTO component_value USING row_value;
    framed := framed || backup_b1_frame(convert_to(component->>'type_identity', 'UTF8'));
    IF component_value IS NULL THEN
      IF NOT (enforcement->>'nulls_not_distinct')::boolean THEN
        RETURN false;
      END IF;
      framed := framed || decode('00', 'hex');
    ELSE
      framed := framed || decode('01', 'hex') || backup_b1_frame(component_value);
    END IF;
  END LOOP;
  SELECT item INTO group_value
    FROM jsonb_array_elements(payload->'component_commitments') AS item
   WHERE item->>'component_id' = reserved_component::text;
  IF group_value IS NULL THEN
    RAISE EXCEPTION 'commitment reservation lacks its component commitment group';
  END IF;
  RETURN (group_value->'commitments') ? encode(
    public.digest(
      convert_to('spaceworks-b1-reservation-v1', 'UTF8')
      || decode(payload->>'reservation_salt', 'base64') || framed,
      'sha256'
    ),
    'hex'
  );
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION backup_b1_enforce_reservations() RETURNS trigger AS $$
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
      FROM backup_b1reservationentry entry
      JOIN backup_b1restorecomponentstate component
        ON component.operation_id = entry.operation_id
       AND component.component_id = entry.component_id
     WHERE component.state <> 'restored'
       AND entry.installed_at IS NOT NULL
       AND COALESCE(
         entry.safe_payload->>'schema',
         entry.safe_payload->'enforcement'->>'schema',
         'public'
       ) = TG_TABLE_SCHEMA
       AND COALESCE(
         entry.safe_payload->>'table',
         entry.safe_payload->'enforcement'->>'table'
       ) = TG_TABLE_NAME
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
          TG_OP = 'UPDATE'
          AND old_row->column_name IS DISTINCT FROM new_row->column_name
        );
      END LOOP;
      IF relevant THEN
        RAISE EXCEPTION 'write is blocked by an opaque object namespace fence';
      END IF;
    END IF;
  END LOOP;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION backup_b1_install_reservation_trigger() RETURNS trigger AS $$
DECLARE
  target_schema text;
  target_table text;
  target_oid regclass;
BEGIN
  IF NEW.installed_at IS NULL THEN
    RETURN NEW;
  END IF;
  target_schema := COALESCE(
    NEW.safe_payload->>'schema', NEW.safe_payload->'enforcement'->>'schema', 'public'
  );
  target_table := COALESCE(
    NEW.safe_payload->>'table', NEW.safe_payload->'enforcement'->>'table'
  );
  IF target_table IS NULL THEN
    RAISE EXCEPTION 'installed reservation lacks a target table';
  END IF;
  target_oid := to_regclass(format('%I.%I', target_schema, target_table));
  IF target_oid IS NULL THEN
    RAISE EXCEPTION 'installed reservation target %.% does not exist', target_schema, target_table;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_trigger
     WHERE tgrelid = target_oid AND tgname = 'backup_b1_reservation_guard'
       AND NOT tgisinternal
  ) THEN
    EXECUTE format(
      'CREATE TRIGGER backup_b1_reservation_guard '
      'BEFORE INSERT OR UPDATE OR DELETE ON %I.%I '
      'FOR EACH ROW EXECUTE FUNCTION backup_b1_enforce_reservations()',
      target_schema, target_table
    );
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;

CREATE TRIGGER backup_b1_install_reservation_trigger
AFTER INSERT OR UPDATE OF installed_at ON backup_b1reservationentry
FOR EACH ROW EXECUTE FUNCTION backup_b1_install_reservation_trigger();
"""


REVERSE = r"""
DROP TRIGGER IF EXISTS backup_b1_install_reservation_trigger ON backup_b1reservationentry;
DO $$
DECLARE
  guarded record;
BEGIN
  FOR guarded IN
    SELECT namespace.nspname AS schema_name, target.relname AS table_name
      FROM pg_catalog.pg_trigger trigger
      JOIN pg_catalog.pg_class target ON target.oid = trigger.tgrelid
      JOIN pg_catalog.pg_namespace namespace ON namespace.oid = target.relnamespace
     WHERE trigger.tgname = 'backup_b1_reservation_guard'
       AND NOT trigger.tgisinternal
  LOOP
    EXECUTE format(
      'DROP TRIGGER backup_b1_reservation_guard ON %I.%I',
      guarded.schema_name, guarded.table_name
    );
  END LOOP;
END;
$$;
DROP FUNCTION IF EXISTS backup_b1_install_reservation_trigger();
DROP FUNCTION IF EXISTS backup_b1_enforce_reservations();
DROP FUNCTION IF EXISTS backup_b1_commitment_matches(jsonb, uuid, jsonb);
DROP FUNCTION IF EXISTS backup_b1_columns_changed(jsonb, jsonb, jsonb);
DROP FUNCTION IF EXISTS backup_b1_frame(bytea);
"""


class Migration(migrations.Migration):
    dependencies = [("backup", "0017_b1_restore_state_guards")]
    operations = [migrations.RunSQL(ENFORCEMENT, REVERSE)]
