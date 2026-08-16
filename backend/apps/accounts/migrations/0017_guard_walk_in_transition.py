"""Enforce the one authorised walk-in-to-account transition at the database.

Any future migration that must change ``is_walk_in`` from true to false must set the
transaction-local ``app.allow_walk_in_transition`` GUC and reproduce the complete
revocation contract: unconsumed claim codes, live claim sessions, active claim-created
presence, SimpleJWT outstanding tokens, and device refresh families.

The trigger is UPDATE-only and fires only for true-to-false changes, so lifecycle and
per-module purges remain unaffected.
"""

from django.db import migrations


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION accounts_guard_walk_in_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF current_setting('app.allow_walk_in_transition', true) = 'on' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'walk-in to account transition requires the accounts transition service';
END;
$$;

CREATE TRIGGER accounts_user_guard_walk_in_transition
BEFORE UPDATE OF is_walk_in ON accounts_user
FOR EACH ROW
WHEN (OLD.is_walk_in IS TRUE AND NEW.is_walk_in IS FALSE)
EXECUTE FUNCTION accounts_guard_walk_in_transition();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS accounts_user_guard_walk_in_transition ON accounts_user;
DROP FUNCTION IF EXISTS accounts_guard_walk_in_transition();
"""


class Migration(migrations.Migration):
    dependencies = [("accounts", "0016_clear_walk_in_email_verification")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
