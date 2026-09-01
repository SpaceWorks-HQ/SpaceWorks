from django.db import migrations


STATE_ORDER_SQL = """
CREATE OR REPLACE FUNCTION audit_rotation_event_state_order_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    prior_state varchar(16);
BEGIN
    -- Serialize lifecycle inserts for one immutable rotation. The FK alone does not
    -- prevent concurrent PUBLISHED and ABORTED inserts from both seeing PREPARED.
    PERFORM 1
    FROM audit_auditsigningkeyrotation
    WHERE id = NEW.rotation_id
    FOR UPDATE;

    SELECT state INTO prior_state
    FROM audit_auditsigningkeyrotationevent
    WHERE rotation_id = NEW.rotation_id
    ORDER BY id DESC
    LIMIT 1;

    IF prior_state IS NULL THEN
        IF NEW.state <> 'PREPARED' THEN
            RAISE EXCEPTION 'first audit signing-key rotation state must be PREPARED';
        END IF;
    ELSIF prior_state = 'PREPARED' THEN
        IF NEW.state NOT IN ('PUBLISHED', 'ABORTED') THEN
            RAISE EXCEPTION 'PREPARED audit signing-key rotation must publish or abort';
        END IF;
    ELSIF prior_state = 'PUBLISHED' THEN
        IF NEW.state <> 'FINALIZED' THEN
            RAISE EXCEPTION 'PUBLISHED audit signing-key rotation must finalize';
        END IF;
    ELSIF prior_state IN ('FINALIZED', 'ABORTED') THEN
        RAISE EXCEPTION 'terminal audit signing-key rotation cannot transition';
    ELSE
        RAISE EXCEPTION 'unknown prior audit signing-key rotation state: %', prior_state;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER audit_rotation_event_state_order
BEFORE INSERT ON audit_auditsigningkeyrotationevent
FOR EACH ROW EXECUTE FUNCTION audit_rotation_event_state_order_guard();
"""


REVERSE_SQL = """
DROP TRIGGER IF EXISTS audit_rotation_event_state_order
ON audit_auditsigningkeyrotationevent;
DROP FUNCTION IF EXISTS audit_rotation_event_state_order_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0006_audit_signing_key_rotation")]

    operations = [migrations.RunSQL(STATE_ORDER_SQL, REVERSE_SQL)]
