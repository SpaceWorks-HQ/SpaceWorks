import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


GUARD_SQL = """
CREATE TRIGGER audit_verification_run_no_update
BEFORE UPDATE ON audit_auditverificationrun
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
CREATE TRIGGER audit_verification_run_no_delete
BEFORE DELETE ON audit_auditverificationrun
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
CREATE TRIGGER audit_verification_run_event_no_update
BEFORE UPDATE ON audit_auditverificationrunevent
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
CREATE TRIGGER audit_verification_run_event_no_delete
BEFORE DELETE ON audit_auditverificationrunevent
FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();

CREATE OR REPLACE FUNCTION audit_verification_event_order_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    prior_state varchar(16);
    prior_attempt integer;
BEGIN
    -- Serialize event inserts per immutable root so two workers cannot both append
    -- after the same prior state.
    PERFORM 1 FROM audit_auditverificationrun WHERE id = NEW.run_id FOR UPDATE;

    SELECT state, attempt INTO prior_state, prior_attempt
    FROM audit_auditverificationrunevent
    WHERE run_id = NEW.run_id
    ORDER BY id DESC
    LIMIT 1;

    IF prior_state IS NULL THEN
        IF NEW.state <> 'QUEUED' OR NEW.attempt <> 0 THEN
            RAISE EXCEPTION 'first audit verification event must be QUEUED(0)';
        END IF;
    ELSIF prior_state = 'QUEUED' THEN
        IF NOT ((NEW.state = 'RUNNING' AND NEW.attempt = 1)
                OR (NEW.state = 'TIMED_OUT' AND NEW.attempt = 0)) THEN
            RAISE EXCEPTION 'QUEUED audit verification must run(1) or time out(0)';
        END IF;
    ELSIF prior_state = 'RUNNING' THEN
        IF NEW.state NOT IN ('SUCCEEDED', 'INCOMPLETE', 'FAILED', 'TIMED_OUT', 'RETRYING')
           OR NEW.attempt <> prior_attempt THEN
            RAISE EXCEPTION 'RUNNING audit verification must finish or retry in its attempt';
        END IF;
    ELSIF prior_state = 'RETRYING' THEN
        IF NOT ((NEW.state = 'RUNNING' AND NEW.attempt = prior_attempt + 1
                 AND NEW.attempt <= 3)
                OR (NEW.state = 'TIMED_OUT' AND NEW.attempt = prior_attempt)) THEN
            RAISE EXCEPTION 'RETRYING audit verification must run the next attempt (<= 3)';
        END IF;
    ELSIF prior_state IN ('SUCCEEDED', 'INCOMPLETE', 'FAILED', 'TIMED_OUT') THEN
        RAISE EXCEPTION 'terminal audit verification run cannot transition';
    ELSE
        RAISE EXCEPTION 'unknown prior audit verification state: %', prior_state;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER audit_verification_event_order
BEFORE INSERT ON audit_auditverificationrunevent
FOR EACH ROW EXECUTE FUNCTION audit_verification_event_order_guard();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS audit_verification_event_order ON audit_auditverificationrunevent;
DROP FUNCTION IF EXISTS audit_verification_event_order_guard();
DROP TRIGGER IF EXISTS audit_verification_run_event_no_delete ON audit_auditverificationrunevent;
DROP TRIGGER IF EXISTS audit_verification_run_event_no_update ON audit_auditverificationrunevent;
DROP TRIGGER IF EXISTS audit_verification_run_no_delete ON audit_auditverificationrun;
DROP TRIGGER IF EXISTS audit_verification_run_no_update ON audit_auditverificationrun;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0008_audit_rotation_abort_retries'),
        ('makerspaces', '0072_enable_charge_tracking_for_existing_makerspaces'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditVerificationRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action_filter', models.CharField(blank=True, max_length=100)),
                ('target_type_filter', models.CharField(blank=True, max_length=200)),
                ('target_id_filter', models.CharField(blank=True, max_length=100)),
                ('actor_filter', models.PositiveBigIntegerField(blank=True, null=True)),
                ('start_at', models.DateTimeField(blank=True, null=True)),
                ('end_at', models.DateTimeField(blank=True, null=True)),
                ('snapshot_max_id', models.PositiveBigIntegerField()),
                ('filter_fingerprint', models.CharField(max_length=64)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('makerspace', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='audit_verification_runs', to='makerspaces.makerspace')),
                ('requested_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='audit_verification_runs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at', '-pk'],
            },
        ),
        migrations.CreateModel(
            name='AuditVerificationRunEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('state', models.CharField(choices=[('QUEUED', 'Queued'), ('RUNNING', 'Running'), ('RETRYING', 'Retrying'), ('SUCCEEDED', 'Succeeded'), ('INCOMPLETE', 'Incomplete'), ('FAILED', 'Failed'), ('TIMED_OUT', 'Timed out')], max_length=16)),
                ('attempt', models.PositiveSmallIntegerField(default=0)),
                ('row_count', models.PositiveIntegerField(default=0)),
                ('mac_valid_count', models.PositiveIntegerField(default=0)),
                ('unattested_count', models.PositiveIntegerField(default=0)),
                ('mac_invalid_count', models.PositiveIntegerField(default=0)),
                ('mac_unavailable_count', models.PositiveIntegerField(default=0)),
                ('unbatched_count', models.PositiveIntegerField(default=0)),
                ('local_batch_verified_count', models.PositiveIntegerField(default=0)),
                ('batch_invalid_count', models.PositiveIntegerField(default=0)),
                ('batch_unavailable_count', models.PositiveIntegerField(default=0)),
                ('externally_anchored_count', models.PositiveIntegerField(default=0)),
                ('chain_status', models.CharField(choices=[('pending', 'Pending'), ('locally_verified', 'Locally verified'), ('invalid', 'Invalid'), ('unavailable', 'Unavailable')], default='pending', max_length=24)),
                ('anchor_status', models.CharField(choices=[('pending', 'Pending'), ('not_configured', 'Not configured'), ('externally_anchored', 'Externally anchored'), ('invalid', 'Invalid'), ('unavailable', 'Unavailable')], default='pending', max_length=24)),
                ('failure_code', models.CharField(blank=True, choices=[('', 'None'), ('anchor_retry_exhausted', 'Anchor retry exhausted'), ('verification_unavailable', 'Verification unavailable'), ('verification_bounds_exceeded', 'Bounds exceeded'), ('database_retry_exhausted', 'Database retry exhausted'), ('task_error', 'Task error'), ('soft_time_limit', 'Soft time limit'), ('stale_run', 'Stale run')], default='', max_length=32)),
                ('first_audit_log_id', models.PositiveBigIntegerField(blank=True, null=True)),
                ('first_batch_seq', models.PositiveBigIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='audit.auditverificationrun')),
            ],
            options={
                'ordering': ['created_at', 'pk'],
            },
        ),
        migrations.AddIndex(
            model_name='auditverificationrun',
            index=models.Index(fields=['makerspace', '-created_at'], name='audit_vrun_space_created'),
        ),
        migrations.AddIndex(
            model_name='auditverificationrun',
            index=models.Index(fields=['makerspace', 'filter_fingerprint'], name='audit_vrun_space_fp'),
        ),
        migrations.AddConstraint(
            model_name='auditverificationrun',
            constraint=models.CheckConstraint(condition=models.Q(('actor_filter__isnull', True), ('actor_filter__gt', 0), _connector='OR'), name='ck_audit_vrun_actor_filter_positive'),
        ),
        migrations.AddIndex(
            model_name='auditverificationrunevent',
            index=models.Index(fields=['run', '-id'], name='audit_vrun_event_latest'),
        ),
        migrations.RunSQL(GUARD_SQL, REVERSE_SQL),
    ]
