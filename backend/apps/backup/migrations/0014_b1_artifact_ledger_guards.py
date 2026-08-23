from django.db import migrations


GUARDS = r"""
CREATE OR REPLACE FUNCTION backup_artifact_ledger_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'backup artifact ledger rows cannot be deleted';
  END IF;
  IF OLD.artifact_id <> NEW.artifact_id
     OR OLD.capture_id <> NEW.capture_id
     OR OLD.archive_uuid_snapshot <> NEW.archive_uuid_snapshot
     OR OLD.outer_sha256 <> NEW.outer_sha256
     OR OLD.outer_manifest_sha256 <> NEW.outer_manifest_sha256
     OR OLD.format <> NEW.format
     OR OLD.outer_manifest <> NEW.outer_manifest
     OR OLD.frozen_promotion_snapshot <> NEW.frozen_promotion_snapshot
     OR OLD.expected_size_bytes <> NEW.expected_size_bytes
     OR OLD.staging_locator <> NEW.staging_locator
     OR OLD.final_locator <> NEW.final_locator
     OR OLD.created_at <> NEW.created_at
     OR NOT (
       OLD.archive_id IS NOT DISTINCT FROM NEW.archive_id
       OR (OLD.archive_id IS NOT NULL AND NEW.archive_id IS NULL)
     )
     OR OLD.predecessor_artifact_id_snapshot IS DISTINCT FROM NEW.predecessor_artifact_id_snapshot
     OR OLD.predecessor_success_at_snapshot IS DISTINCT FROM NEW.predecessor_success_at_snapshot THEN
    RAISE EXCEPTION 'immutable backup artifact facts cannot be changed';
  END IF;
  IF (OLD.staging_verified_at IS NOT NULL AND OLD.staging_verified_at IS DISTINCT FROM NEW.staging_verified_at)
     OR (OLD.staging_verified_size_bytes IS NOT NULL AND OLD.staging_verified_size_bytes IS DISTINCT FROM NEW.staging_verified_size_bytes)
     OR (OLD.staging_verified_sha256 <> '' AND OLD.staging_verified_sha256 <> NEW.staging_verified_sha256)
     OR (OLD.final_verified_at IS NOT NULL AND OLD.final_verified_at IS DISTINCT FROM NEW.final_verified_at)
     OR (OLD.final_verified_size_bytes IS NOT NULL AND OLD.final_verified_size_bytes IS DISTINCT FROM NEW.final_verified_size_bytes)
     OR (OLD.final_verified_sha256 <> '' AND OLD.final_verified_sha256 <> NEW.final_verified_sha256)
     OR (OLD.promoted_at IS NOT NULL AND OLD.promoted_at IS DISTINCT FROM NEW.promoted_at)
     OR (OLD.superseded_at IS NOT NULL AND OLD.superseded_at IS DISTINCT FROM NEW.superseded_at)
     OR (OLD.bytes_deleted_at IS NOT NULL AND OLD.bytes_deleted_at IS DISTINCT FROM NEW.bytes_deleted_at)
     OR (OLD.failed_at IS NOT NULL AND OLD.failed_at IS DISTINCT FROM NEW.failed_at)
     OR (OLD.failure_code <> '' AND OLD.failure_code <> NEW.failure_code) THEN
    RAISE EXCEPTION 'backup artifact verification facts cannot be changed';
  END IF;
  IF NOT (
    OLD.state = NEW.state
    OR (OLD.state = 'pending' AND NEW.state IN ('staging_verified', 'final_verified', 'failed'))
    OR (OLD.state = 'staging_verified' AND NEW.state IN ('final_verified', 'failed'))
    OR (OLD.state = 'final_verified' AND NEW.state IN ('available', 'failed'))
    OR (OLD.state = 'available' AND NEW.state IN ('superseded', 'bytes_deleted'))
    OR (OLD.state = 'superseded' AND NEW.state = 'bytes_deleted')
  ) THEN
    RAISE EXCEPTION 'invalid backup artifact state transition';
  END IF;
  IF (NEW.state = 'staging_verified'
      AND (NEW.staging_verified_at IS NULL OR NEW.staging_verified_size_bytes IS NULL OR NEW.staging_verified_sha256 = ''))
     OR (NEW.state IN ('final_verified', 'available', 'superseded', 'bytes_deleted')
      AND (NEW.final_verified_at IS NULL OR NEW.final_verified_size_bytes IS NULL OR NEW.final_verified_sha256 = ''))
     OR (NEW.state IN ('available', 'superseded', 'bytes_deleted') AND NEW.promoted_at IS NULL)
     OR (NEW.state = 'superseded' AND NEW.superseded_at IS NULL)
     OR (NEW.state = 'bytes_deleted' AND NEW.bytes_deleted_at IS NULL)
     OR (NEW.state = 'failed' AND (NEW.failed_at IS NULL OR NEW.failure_code = '')) THEN
    RAISE EXCEPTION 'backup artifact state facts are incomplete';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER backup_artifact_ledger_lifecycle
BEFORE UPDATE OR DELETE ON backup_backupartifactledger
FOR EACH ROW EXECUTE FUNCTION backup_artifact_ledger_guard();

CREATE OR REPLACE FUNCTION backup_component_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'backup artifact components cannot be deleted';
  END IF;
  IF OLD.artifact_id <> NEW.artifact_id
     OR OLD.component_id <> NEW.component_id
     OR OLD.kind <> NEW.kind
     OR OLD.makerspace_id_snapshot IS DISTINCT FROM NEW.makerspace_id_snapshot
     OR OLD.ciphertext_path <> NEW.ciphertext_path
     OR OLD.ciphertext_sha256 <> NEW.ciphertext_sha256
     OR OLD.size_bytes <> NEW.size_bytes
     OR OLD.created_at <> NEW.created_at THEN
    RAISE EXCEPTION 'immutable backup component facts cannot be changed';
  END IF;
  IF NOT (
    OLD.storage_state = NEW.storage_state
    OR (OLD.storage_state = 'pending' AND NEW.storage_state = 'available')
    OR (OLD.storage_state = 'available' AND NEW.storage_state = 'bytes_deleted')
  ) THEN
    RAISE EXCEPTION 'invalid backup component state transition';
  END IF;
  IF (NEW.storage_state IN ('available', 'bytes_deleted') AND NEW.available_at IS NULL)
     OR (NEW.storage_state = 'bytes_deleted' AND NEW.bytes_deleted_at IS NULL) THEN
    RAISE EXCEPTION 'backup component state facts are incomplete';
  END IF;
  IF (OLD.available_at IS NOT NULL AND OLD.available_at IS DISTINCT FROM NEW.available_at)
     OR (OLD.bytes_deleted_at IS NOT NULL AND OLD.bytes_deleted_at IS DISTINCT FROM NEW.bytes_deleted_at) THEN
    RAISE EXCEPTION 'backup component lifecycle facts cannot be changed';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER backup_artifact_component_lifecycle
BEFORE UPDATE OR DELETE ON backup_backupartifactcomponent
FOR EACH ROW EXECUTE FUNCTION backup_component_guard();

CREATE OR REPLACE FUNCTION backup_component_recipient_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'backup component recipient history cannot be deleted';
  END IF;
  IF OLD.component_id <> NEW.component_id OR OLD.fingerprint <> NEW.fingerprint
     OR OLD.associated_at <> NEW.associated_at
     OR (OLD.tombstoned_at IS NOT NULL AND NEW.tombstoned_at IS DISTINCT FROM OLD.tombstoned_at) THEN
    RAISE EXCEPTION 'immutable backup component recipient facts cannot be changed';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER backup_component_recipient_lifecycle
BEFORE UPDATE OR DELETE ON backup_backupcomponentrecipient
FOR EACH ROW EXECUTE FUNCTION backup_component_recipient_guard();
"""

REVERSE = r"""
DROP TRIGGER IF EXISTS backup_component_recipient_lifecycle ON backup_backupcomponentrecipient;
DROP FUNCTION IF EXISTS backup_component_recipient_guard();
DROP TRIGGER IF EXISTS backup_artifact_component_lifecycle ON backup_backupartifactcomponent;
DROP FUNCTION IF EXISTS backup_component_guard();
DROP TRIGGER IF EXISTS backup_artifact_ledger_lifecycle ON backup_backupartifactledger;
DROP FUNCTION IF EXISTS backup_artifact_ledger_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("backup", "0013_backfill_b1_activation_state")]

    operations = [migrations.RunSQL(GUARDS, reverse_sql=REVERSE)]
