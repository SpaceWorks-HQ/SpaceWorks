"""Frozen report facts; lifecycle/telemetry and adapter SET_NULL edges may move."""
GUARD_SQL = """
CREATE FUNCTION pii_fence_printer_job() RETURNS trigger LANGUAGE plpgsql AS $printer_pii$
BEGIN
  PERFORM pii_assert_mapped_write_allowed(NEW.makerspace_id);
  RETURN NEW;
END; $printer_pii$;
CREATE TRIGGER pii_fence_printer_job_trigger BEFORE INSERT OR UPDATE OF failure_reason ON devices_printerjob
FOR EACH ROW EXECUTE FUNCTION pii_fence_printer_job();

CREATE FUNCTION devices_printer_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_setting('app.allow_immutable_delete', true) = 'on' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'printer history requires authorized purge';
  END IF;
  IF ROW(OLD.command_id, OLD.device_id, OLD.makerspace_id, OLD.external_job_id,
         OLD.machine_id_snapshot, OLD.machine_name, OLD.service_request_id_snapshot, OLD.service_request_name)
     IS DISTINCT FROM
     ROW(NEW.command_id, NEW.device_id, NEW.makerspace_id, NEW.external_job_id,
         NEW.machine_id_snapshot, NEW.machine_name, NEW.service_request_id_snapshot, NEW.service_request_name) THEN
    RAISE EXCEPTION 'printer identity is immutable';
  END IF;
  IF (NEW.machine_id IS NOT NULL AND NEW.machine_id IS DISTINCT FROM OLD.machine_id) OR
     (NEW.service_request_id IS NOT NULL AND NEW.service_request_id IS DISTINCT FROM OLD.service_request_id) THEN
    RAISE EXCEPTION 'printer target is immutable';
  END IF;
  IF OLD.reported_at IS NOT NULL THEN
    IF ROW(OLD.terminal_operation_id, OLD.report_sha256, OLD.outcome, OLD.actual_minutes,
           OLD.percent_complete, OLD.actual_grams, OLD.actual_quantity, OLD.reported_at)
       IS DISTINCT FROM
       ROW(NEW.terminal_operation_id, NEW.report_sha256, NEW.outcome, NEW.actual_minutes,
           NEW.percent_complete, NEW.actual_grams, NEW.actual_quantity, NEW.reported_at) THEN
      RAISE EXCEPTION 'printer report is immutable';
    END IF;
    -- Authorized PII re-encryption may change ciphertext; adapter verifies plaintext hash.
    IF OLD.failure_reason IS DISTINCT FROM NEW.failure_reason AND
       COALESCE(current_setting('app.pii_fence_operation', true), '') = '' THEN
      RAISE EXCEPTION 'printer failure report is immutable';
    END IF;
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER devices_printer_job_guard BEFORE UPDATE OR DELETE ON devices_printerjob
FOR EACH ROW EXECUTE FUNCTION devices_printer_job_guard();

CREATE FUNCTION devices_printer_consumption_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_setting('app.allow_immutable_delete', true) = 'on' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'printer consumption requires authorized purge';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF EXISTS (SELECT 1 FROM devices_printerjob WHERE id = NEW.job_id AND reported_at IS NOT NULL)
       AND COALESCE(current_setting('app.printer_claim_job', true), '') <> NEW.job_id::text
       AND COALESCE(current_setting('app.pii_fence_operation', true), '') = '' THEN
      RAISE EXCEPTION 'printer consumption report is immutable';
    END IF;
    RETURN NEW;
  END IF;
  IF ROW(OLD.job_id, OLD.machine_consumable_id_snapshot, OLD.quantity)
     IS DISTINCT FROM ROW(NEW.job_id, NEW.machine_consumable_id_snapshot, NEW.quantity) OR
     (NEW.machine_consumable_id IS NOT NULL AND NEW.machine_consumable_id IS DISTINCT FROM OLD.machine_consumable_id) THEN
    RAISE EXCEPTION 'printer consumption report is immutable';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER devices_printer_consumption_guard BEFORE INSERT OR UPDATE OR DELETE ON devices_printerjobconsumption
FOR EACH ROW EXECUTE FUNCTION devices_printer_consumption_guard();

CREATE FUNCTION devices_command_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF ROW(OLD.device_id, OLD.makerspace_id, OLD.kind, OLD.device_key_version)
     IS DISTINCT FROM ROW(NEW.device_id, NEW.makerspace_id, NEW.kind, NEW.device_key_version) THEN
    RAISE EXCEPTION 'command ownership is immutable';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER devices_command_identity_guard BEFORE UPDATE ON devices_devicecommand
FOR EACH ROW EXECUTE FUNCTION devices_command_identity_guard();
"""

DROP_GUARD_SQL = """
DROP TRIGGER IF EXISTS pii_fence_printer_job_trigger ON devices_printerjob;
DROP FUNCTION IF EXISTS pii_fence_printer_job();
DROP TRIGGER IF EXISTS devices_command_identity_guard ON devices_devicecommand;
DROP FUNCTION IF EXISTS devices_command_identity_guard();
DROP TRIGGER IF EXISTS devices_printer_consumption_guard ON devices_printerjobconsumption;
DROP FUNCTION IF EXISTS devices_printer_consumption_guard();
DROP TRIGGER IF EXISTS devices_printer_job_guard ON devices_printerjob;
DROP FUNCTION IF EXISTS devices_printer_job_guard();
"""
