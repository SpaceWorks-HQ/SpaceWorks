from django.db import migrations


STATE_GUARDS = r"""
ALTER TABLE backup_b1restorecomponentstate
  ADD CONSTRAINT backup_b1_component_operation_fk
  FOREIGN KEY (operation_id) REFERENCES backup_b1restoreoperationstate(operation_id)
  ON DELETE RESTRICT;
ALTER TABLE backup_b1reservationentry
  ADD CONSTRAINT backup_b1_reservation_component_fk
  FOREIGN KEY (operation_id, component_id)
  REFERENCES backup_b1restorecomponentstate(operation_id, component_id)
  ON DELETE RESTRICT;
ALTER TABLE backup_b1fencecontinuity
  ADD CONSTRAINT backup_b1_continuity_operation_fk
  FOREIGN KEY (operation_id) REFERENCES backup_b1restoreoperationstate(operation_id)
  ON DELETE RESTRICT;

CREATE FUNCTION backup_b1_restore_operation_guard() RETURNS trigger AS $$
DECLARE
  old_rank integer;
  new_rank integer;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'compound restore operation state cannot be deleted';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.stage <> 'verified' THEN
      RAISE EXCEPTION 'compound restore operation must begin at verified';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.operation_id <> NEW.operation_id
     OR OLD.artifact_id <> NEW.artifact_id
     OR OLD.capture_id <> NEW.capture_id
     OR OLD.main_component_id <> NEW.main_component_id
     OR OLD.outer_ciphertext_sha256 <> NEW.outer_ciphertext_sha256
     OR OLD.outer_manifest_sha256 <> NEW.outer_manifest_sha256
     OR OLD.source_proof_sha256 <> NEW.source_proof_sha256
     OR OLD.sibling_database_name <> NEW.sibling_database_name
     OR OLD.sibling_database_oid <> NEW.sibling_database_oid
     OR OLD.sibling_server_identity <> NEW.sibling_server_identity
     OR OLD.created_at <> NEW.created_at THEN
    RAISE EXCEPTION 'compound restore operation identity is immutable';
  END IF;
  IF OLD.fence_continuity_digest <> ''
     AND OLD.fence_continuity_digest <> NEW.fence_continuity_digest
     OR OLD.object_journal_evidence_sha256 <> ''
     AND OLD.object_journal_evidence_sha256 <> NEW.object_journal_evidence_sha256
     OR OLD.quarantine_evidence_sha256 <> ''
     AND OLD.quarantine_evidence_sha256 <> NEW.quarantine_evidence_sha256
     OR OLD.cutover_attestation <> '{}'::jsonb
     AND OLD.cutover_attestation <> NEW.cutover_attestation
     OR OLD.failure_code <> '' AND OLD.failure_code <> NEW.failure_code THEN
    RAISE EXCEPTION 'compound restore evidence is immutable once recorded';
  END IF;
  IF OLD.stage = NEW.stage THEN
    RETURN NEW;
  END IF;
  IF OLD.stage = 'failed' OR NEW.stage = 'verified' THEN
    RAISE EXCEPTION 'compound restore stage cannot move backwards';
  END IF;
  IF NEW.stage = 'failed' THEN
    IF NEW.failure_code = '' THEN
      RAISE EXCEPTION 'failed compound restore stage requires a failure code';
    END IF;
    RETURN NEW;
  END IF;
  old_rank := array_position(ARRAY[
    'verified', 'main_restored', 'roles_recreated', 'state_rehydrated',
    'enforcement_installed', 'catalog_verified', 'objects_verified',
    'quarantine_verified', 'cutover_ready'
  ], OLD.stage);
  new_rank := array_position(ARRAY[
    'verified', 'main_restored', 'roles_recreated', 'state_rehydrated',
    'enforcement_installed', 'catalog_verified', 'objects_verified',
    'quarantine_verified', 'cutover_ready'
  ], NEW.stage);
  IF old_rank IS NULL OR new_rank <> old_rank + 1 THEN
    RAISE EXCEPTION 'compound restore stages must advance exactly one step';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION backup_b1_restore_component_guard() RETURNS trigger AS $$
DECLARE
  operation_record backup_b1restoreoperationstate%ROWTYPE;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'restore component state cannot be deleted';
  END IF;
  IF TG_OP = 'INSERT' THEN
    SELECT * INTO STRICT operation_record
      FROM backup_b1restoreoperationstate WHERE operation_id = NEW.operation_id;
    IF operation_record.artifact_id <> NEW.artifact_id
       OR operation_record.capture_id <> NEW.capture_id THEN
      RAISE EXCEPTION 'restore component binding does not match its operation';
    END IF;
    IF NEW.state <> 'pending' THEN
      RAISE EXCEPTION 'restore component must begin pending';
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
  IF OLD.state = NEW.state THEN
    RETURN NEW;
  END IF;
  -- The CASE must be parenthesised: PL/pgSQL scans an IF condition up to the
  -- first THEN, and an unparenthesised CASE supplies its own THEN keywords,
  -- which truncates the condition and fails with "syntax error at end of input".
  IF NOT (CASE OLD.state
    WHEN 'pending' THEN NEW.state IN ('dependency_wait', 'merging', 'failed')
    WHEN 'dependency_wait' THEN NEW.state IN ('pending', 'merging', 'failed')
    WHEN 'merging' THEN NEW.state IN ('restored', 'failed')
    ELSE false
  END) THEN
    RAISE EXCEPTION 'invalid restore component state transition: % -> %', OLD.state, NEW.state;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION backup_b1_reservation_state_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'restore reservations cannot be deleted';
  END IF;
  IF OLD.operation_id <> NEW.operation_id OR OLD.component_id <> NEW.component_id
     OR OLD.registry_identity <> NEW.registry_identity OR OLD.kind <> NEW.kind
     OR OLD.definition_sha256 <> NEW.definition_sha256
     OR OLD.safe_payload <> NEW.safe_payload
     OR OLD.installed_at IS NOT NULL AND OLD.installed_at IS DISTINCT FROM NEW.installed_at
     OR OLD.catalog_verified_at IS NOT NULL
        AND OLD.catalog_verified_at IS DISTINCT FROM NEW.catalog_verified_at THEN
    RAISE EXCEPTION 'restore reservation facts are immutable';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION backup_b1_fence_continuity_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'fence continuity records cannot be deleted';
  END IF;
  IF OLD.operation_id <> NEW.operation_id
     OR OLD.registry_identity <> NEW.registry_identity
     OR OLD.definition_sha256 <> NEW.definition_sha256
     OR OLD.trigger_oids <> NEW.trigger_oids OR OLD.installed_at <> NEW.installed_at
     OR NEW.enabled IS NOT TRUE OR NEW.last_verified_at < OLD.last_verified_at THEN
    RAISE EXCEPTION 'fence continuity facts are immutable';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION backup_b1_reject_pending_makerspace_materialization() RETURNS trigger AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM backup_b1restorecomponentstate
     WHERE makerspace_id_snapshot = NEW.id AND state <> 'restored'
  ) THEN
    RAISE EXCEPTION 'makerspace is persistently not restored';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER backup_b1_restore_operation_guard
BEFORE INSERT OR UPDATE OR DELETE ON backup_b1restoreoperationstate
FOR EACH ROW EXECUTE FUNCTION backup_b1_restore_operation_guard();
CREATE TRIGGER backup_b1_restore_component_guard
BEFORE INSERT OR UPDATE OR DELETE ON backup_b1restorecomponentstate
FOR EACH ROW EXECUTE FUNCTION backup_b1_restore_component_guard();
CREATE TRIGGER backup_b1_reservation_state_guard
BEFORE UPDATE OR DELETE ON backup_b1reservationentry
FOR EACH ROW EXECUTE FUNCTION backup_b1_reservation_state_guard();
CREATE TRIGGER backup_b1_fence_continuity_guard
BEFORE UPDATE OR DELETE ON backup_b1fencecontinuity
FOR EACH ROW EXECUTE FUNCTION backup_b1_fence_continuity_guard();
CREATE TRIGGER backup_b1_pending_makerspace_guard
BEFORE INSERT OR UPDATE OF id ON makerspaces_makerspace
FOR EACH ROW EXECUTE FUNCTION backup_b1_reject_pending_makerspace_materialization();
"""


REVERSE = r"""
DROP TRIGGER IF EXISTS backup_b1_pending_makerspace_guard ON makerspaces_makerspace;
DROP TRIGGER IF EXISTS backup_b1_fence_continuity_guard ON backup_b1fencecontinuity;
DROP TRIGGER IF EXISTS backup_b1_reservation_state_guard ON backup_b1reservationentry;
DROP TRIGGER IF EXISTS backup_b1_restore_component_guard ON backup_b1restorecomponentstate;
DROP TRIGGER IF EXISTS backup_b1_restore_operation_guard ON backup_b1restoreoperationstate;
DROP FUNCTION IF EXISTS backup_b1_fence_continuity_guard();
DROP FUNCTION IF EXISTS backup_b1_reservation_state_guard();
DROP FUNCTION IF EXISTS backup_b1_restore_component_guard();
DROP FUNCTION IF EXISTS backup_b1_restore_operation_guard();
DROP FUNCTION IF EXISTS backup_b1_reject_pending_makerspace_materialization();
ALTER TABLE backup_b1fencecontinuity DROP CONSTRAINT IF EXISTS backup_b1_continuity_operation_fk;
ALTER TABLE backup_b1reservationentry DROP CONSTRAINT IF EXISTS backup_b1_reservation_component_fk;
ALTER TABLE backup_b1restorecomponentstate DROP CONSTRAINT IF EXISTS backup_b1_component_operation_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("backup", "0016_b1_restore_reservations")]
    operations = [migrations.RunSQL(STATE_GUARDS, REVERSE)]
