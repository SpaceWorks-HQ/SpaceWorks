"""DB guards for immutable request claims and append-only result receipts."""
GUARD_SQL = """
CREATE OR REPLACE FUNCTION devices_label_claim_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_setting('app.allow_immutable_delete', true) = 'on' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'label history requires authorized purge';
  END IF;
  IF (NEW.command_id, NEW.makerspace_id, NEW.device_id, NEW.request_id,
      NEW.batch_id_snapshot, NEW.batch_title_snapshot, NEW.item_count_snapshot, NEW.created_at)
     IS DISTINCT FROM
     (OLD.command_id, OLD.makerspace_id, OLD.device_id, OLD.request_id,
      OLD.batch_id_snapshot, OLD.batch_title_snapshot, OLD.item_count_snapshot, OLD.created_at) THEN
    RAISE EXCEPTION 'label request claims are immutable';
  END IF;
  IF (NEW.batch_id IS NOT NULL AND NEW.batch_id IS DISTINCT FROM OLD.batch_id) OR
     (NEW.requested_by_id IS NOT NULL AND NEW.requested_by_id IS DISTINCT FROM OLD.requested_by_id) THEN
    RAISE EXCEPTION 'label request target and requester are immutable';
  END IF;
  IF OLD.result IN ('succeeded', 'failed') AND
     (NEW.result, NEW.result_code, NEW.result_message, NEW.completed_at) IS DISTINCT FROM
     (OLD.result, OLD.result_code, OLD.result_message, OLD.completed_at) THEN
    RAISE EXCEPTION 'terminal label outcomes are immutable';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER devices_label_claim_guard BEFORE UPDATE OR DELETE ON devices_labelprintcommand
FOR EACH ROW EXECUTE FUNCTION devices_label_claim_guard();
CREATE OR REPLACE FUNCTION devices_label_result_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('app.allow_immutable_delete', true) = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'label result receipts are immutable';
END; $$;
CREATE TRIGGER devices_label_result_guard BEFORE UPDATE OR DELETE ON devices_labelprintresult
FOR EACH ROW EXECUTE FUNCTION devices_label_result_guard();
"""

DROP_GUARD_SQL = """
DROP TRIGGER IF EXISTS devices_label_result_guard ON devices_labelprintresult;
DROP FUNCTION IF EXISTS devices_label_result_guard();
DROP TRIGGER IF EXISTS devices_label_claim_guard ON devices_labelprintcommand;
DROP FUNCTION IF EXISTS devices_label_claim_guard();
"""
