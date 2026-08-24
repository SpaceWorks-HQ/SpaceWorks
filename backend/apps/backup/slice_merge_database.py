"""PostgreSQL role and row trigger that enforce E8 fill-only writes."""

from contextlib import contextmanager
import hashlib

from django.db import connections

from apps.backup.slice_merge_types import SliceMergeError


MERGE_ROLE = "spaceworks_b1_merge"
WRITE_TRIGGER = "backup_b1_merge_write_guard"


ROLE_SQL = r"""
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'spaceworks_b1_merge') THEN
    CREATE ROLE spaceworks_b1_merge NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOINHERIT NOREPLICATION NOBYPASSRLS;
    EXECUTE format('GRANT spaceworks_b1_merge TO %I', session_user);
  ELSIF NOT pg_has_role(session_user, 'spaceworks_b1_merge', 'MEMBER') THEN
    EXECUTE format('GRANT spaceworks_b1_merge TO %I', session_user);
  END IF;
END $$;
REVOKE CREATE ON SCHEMA public FROM spaceworks_b1_merge;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM spaceworks_b1_merge;
GRANT USAGE ON SCHEMA public TO spaceworks_b1_merge;
GRANT SELECT ON public.backup_b1restorecomponentstate,
  public.backup_b1reservationentry
  TO spaceworks_b1_merge;

CREATE OR REPLACE FUNCTION public.backup_b1_merge_write_guard() RETURNS trigger AS $$
DECLARE
  operation_value text := current_setting('app.b1_merge_operation', true);
  component_value text := current_setting('app.b1_merge_component', true);
  stage_schema text := current_setting('app.b1_merge_schema', true);
  permitted boolean := false;
  context_ok boolean := false;
  changed record;
BEGIN
  IF current_user <> 'spaceworks_b1_merge' THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF operation_value IS NULL OR component_value IS NULL OR stage_schema IS NULL
     OR stage_schema !~ '^b1_merge_[0-9a-f_]+$' THEN
    RAISE EXCEPTION 'the merge role requires an operation-owned session context';
  END IF;
  EXECUTE format(
    'SELECT EXISTS (SELECT 1 FROM %I.backup_b1_context '
    'WHERE operation_id = $1::uuid AND component_id = $2::uuid)', stage_schema
  ) INTO context_ok USING operation_value, component_value;
  IF NOT context_ok OR NOT EXISTS (
    SELECT 1 FROM public.backup_b1restorecomponentstate component
     WHERE component.operation_id::text = operation_value
       AND component.component_id::text = component_value
       AND component.state = 'merging'
  ) THEN
    RAISE EXCEPTION 'the merge role context is not an active locked component';
  END IF;
  IF TG_OP = 'INSERT' THEN
    EXECUTE format(
      'SELECT EXISTS (SELECT 1 FROM %I.%I staged '
      'WHERE staged.__b1_component_id = $1::uuid '
      'AND to_jsonb(staged) - ''__b1_component_id'' = to_jsonb($2))',
      stage_schema, TG_TABLE_NAME
    ) INTO permitted USING component_value, NEW;
  ELSIF TG_OP = 'UPDATE' THEN
    permitted := true;
    FOR changed IN
      SELECT old_value.key AS column_name, old_value.value AS before_value,
             new_value.value AS after_value
        FROM jsonb_each(to_jsonb(OLD)) old_value
        JOIN jsonb_each(to_jsonb(NEW)) new_value USING (key)
       WHERE old_value.value IS DISTINCT FROM new_value.value
    LOOP
      EXECUTE format(
        'SELECT EXISTS (SELECT 1 FROM %I.backup_b1_deltas '
        'WHERE component_id = $1::uuid AND table_name = $2 '
        'AND row_pk = to_jsonb($3)->$4 AND column_name = $5 '
        'AND old_value = $6 AND new_value = $7)', stage_schema
      ) INTO context_ok USING component_value, TG_TABLE_NAME, NEW, TG_ARGV[0],
        changed.column_name, changed.before_value, changed.after_value;
      permitted := permitted AND context_ok;
    END LOOP;
  END IF;
  IF NOT permitted THEN
    RAISE EXCEPTION 'the merge role attempted a non-staged or non-delta write';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;
"""


def merge_schema_name(operation_id, component_ids):
    suffix = hashlib.sha256("|".join(sorted(map(str, component_ids))).encode()).hexdigest()[:12]
    return f"b1_merge_{str(operation_id).replace('-', '')[:16]}_{suffix}"


def provision_merge_role(*, using="default"):
    try:
        with connections[using].cursor() as cursor:
            cursor.execute(ROLE_SQL)
    except Exception:
        raise SliceMergeError("The database merge role could not be provisioned safely.") from None


def protect_target_tables(schema, tables, *, using="default"):
    connection = connections[using]
    quote = connection.ops.quote_name
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"GRANT USAGE ON SCHEMA {quote(schema)} TO {MERGE_ROLE}")
            cursor.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {quote(schema)} TO {MERGE_ROLE}")
            for table in sorted(set(tables)):
                target = f"public.{quote(table)}"
                cursor.execute(f"GRANT INSERT, UPDATE ON TABLE {target} TO {MERGE_ROLE}")
                cursor.execute(
                    "SELECT attribute.attname FROM pg_catalog.pg_index index "
                    "JOIN pg_catalog.pg_attribute attribute ON attribute.attrelid = index.indrelid "
                    "AND attribute.attnum = ANY(index.indkey) "
                    "WHERE index.indrelid = %s::regclass AND index.indisprimary",
                    [f"public.{table}"],
                )
                primary = cursor.fetchone()
                if primary is None:
                    raise SliceMergeError("A merge target table has no database primary key.")
                cursor.execute(
                    f"GRANT SELECT ({quote(primary[0])}) ON TABLE {target} TO {MERGE_ROLE}"
                )
                cursor.execute(f"DROP TRIGGER IF EXISTS {WRITE_TRIGGER} ON {target}")
                cursor.execute(
                    f"CREATE TRIGGER {WRITE_TRIGGER} BEFORE INSERT OR UPDATE OR DELETE "
                    f"ON {target} FOR EACH ROW EXECUTE FUNCTION "
                    f"public.backup_b1_merge_write_guard("
                    f"'{primary[0].replace(chr(39), chr(39) * 2)}')"
                )
            cursor.execute(
                f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {MERGE_ROLE}"
            )
    except Exception:
        raise SliceMergeError("Database-level fill-only merge enforcement could not be installed.") from None


@contextmanager
def merge_role(cursor, operation_id, component_id, schema):
    """Enter the NOLOGIN role with facts consumed by database triggers."""
    try:
        cursor.execute(f"SET LOCAL ROLE {MERGE_ROLE}")
        cursor.execute("SELECT set_config('app.b1_merge_operation', %s, true)", [str(operation_id)])
        cursor.execute("SELECT set_config('app.b1_merge_component', %s, true)", [str(component_id)])
        cursor.execute("SELECT set_config('app.b1_merge_schema', %s, true)", [schema])
        cursor.execute("SELECT set_config('app.allow_immutable_insert', 'on', true)")
        yield
    except Exception as exc:
        if isinstance(exc, SliceMergeError):
            raise
        raise SliceMergeError("The database merge role refused a non-fill-only write.") from None
    finally:
        try:
            cursor.execute("RESET ROLE")
        except Exception:
            pass


def advisory_key(operation_id, component_id):
    digest = hashlib.sha256(f"{operation_id}:{component_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@contextmanager
def component_locks(operation_id, component_ids, *, using="default"):
    """Hold one ordered session lock per component across remote merge steps."""
    connection = connections[using]
    connection.ensure_connection()
    keys = sorted({
        -(2**63) + 8048,
        *(advisory_key(operation_id, value) for value in component_ids),
    })
    with connection.cursor() as cursor:
        for key in keys:
            cursor.execute("SELECT pg_advisory_lock(%s)", [key])
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            for key in reversed(keys):
                cursor.execute("SELECT pg_advisory_unlock(%s)", [key])
