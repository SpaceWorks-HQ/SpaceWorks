from django.db import migrations


SQL = """
CREATE OR REPLACE FUNCTION apiclients_reject_import_approval_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('app.allow_immutable_delete', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'API-client import approval is append-only';
END;
$$;
CREATE TRIGGER apiclients_import_approval_no_update
BEFORE UPDATE ON apiclients_apiclientimportapproval
FOR EACH ROW EXECUTE FUNCTION apiclients_reject_import_approval_mutation();
CREATE TRIGGER apiclients_import_approval_no_delete
BEFORE DELETE ON apiclients_apiclientimportapproval
FOR EACH ROW EXECUTE FUNCTION apiclients_reject_import_approval_mutation();
"""

REVERSE = """
DROP TRIGGER IF EXISTS apiclients_import_approval_no_delete
ON apiclients_apiclientimportapproval;
DROP TRIGGER IF EXISTS apiclients_import_approval_no_update
ON apiclients_apiclientimportapproval;
DROP FUNCTION IF EXISTS apiclients_reject_import_approval_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("apiclients", "0007_lane_d_import_approval")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
