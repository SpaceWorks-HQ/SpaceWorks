# Phase 9c: source-local coordination only; no payload/response/PII storage.
from uuid import uuid4
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('hardware_requests', '0024_anonymous_request_submission'),
        ('makerspaces', '0074_station_operator_leases'),
        ('evidence', '0006_evidence_retention'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ReplayCommand',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid4, editable=False, serialize=False)),
                ('makerspace', models.ForeignKey('makerspaces.Makerspace', on_delete=models.CASCADE)),
                ('station', models.ForeignKey('makerspaces.Station', on_delete=models.PROTECT)),
                ('actor', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)),
                ('operator_lease_id', models.UUIDField()),
                ('station_session_id', models.UUIDField()),
                ('station_version', models.PositiveIntegerField()),
                ('client_command_id', models.UUIDField()),
                ('payload_fingerprint', models.CharField(max_length=64)),
                ('operation_kind', models.CharField(max_length=24)),
                ('operation_version', models.PositiveIntegerField()),
                ('aggregate_id', models.UUIDField()),
                ('sequence', models.PositiveIntegerField()),
                ('predecessor', models.ForeignKey('hardware_requests.replaycommand', null=True, blank=True, on_delete=models.PROTECT, related_name='successors')),
                ('state', models.CharField(max_length=12, choices=[('prepared', 'Prepared'), ('claimed', 'Claimed'), ('succeeded', 'Succeeded'), ('failed', 'Failed')], default='prepared')),
                ('claim_token', models.UUIDField(null=True, blank=True)),
                ('claimed_at', models.DateTimeField(null=True, blank=True)),
                ('claim_attempts', models.PositiveIntegerField(default=0)),
                ('client_created_at', models.DateTimeField()),
                ('expires_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(null=True, blank=True)),
                ('failure_code', models.CharField(max_length=64, null=True, blank=True)),
                ('failure_detail', models.CharField(max_length=200, null=True, blank=True)),
                ('subject_request', models.ForeignKey('hardware_requests.HardwareRequest', null=True, blank=True, on_delete=models.PROTECT, related_name='subject_replays')),
                ('subject_loan', models.ForeignKey('hardware_requests.PublicToolLoan', null=True, blank=True, on_delete=models.PROTECT, related_name='subject_replays')),
                ('evidence', models.ForeignKey('evidence.EvidencePhoto', null=True, blank=True, on_delete=models.PROTECT)),
                ('result_request', models.ForeignKey('hardware_requests.HardwareRequest', null=True, blank=True, on_delete=models.PROTECT, related_name='result_replays')),
                ('result_loan', models.ForeignKey('hardware_requests.PublicToolLoan', null=True, blank=True, on_delete=models.PROTECT, related_name='result_replays')),
                ('result_return_event', models.ForeignKey('hardware_requests.ReturnEvent', null=True, blank=True, on_delete=models.PROTECT)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('station', 'station_session_id', 'client_command_id'), name='replay_owner_command_unique'), models.UniqueConstraint(fields=('station', 'station_session_id', 'aggregate_id', 'sequence'), name='replay_stream_position_unique'), models.CheckConstraint(condition=models.Q(sequence__gt=0, operation_version__gt=0), name='replay_positive_protocol'), models.CheckConstraint(condition=models.Q(state='claimed', claim_token__isnull=False, claimed_at__isnull=False) | ~models.Q(state='claimed') & models.Q(claim_token__isnull=True, claimed_at__isnull=True), name='replay_claim_consistent'), models.CheckConstraint(condition=models.Q(state__in=('succeeded', 'failed'), completed_at__isnull=False) | models.Q(state__in=('prepared', 'claimed'), completed_at__isnull=True), name='replay_completion_consistent'), models.CheckConstraint(condition=models.Q(state='failed', failure_code__isnull=False, failure_detail__isnull=False) | ~models.Q(state='failed') & models.Q(failure_code__isnull=True, failure_detail__isnull=True), name='replay_failure_consistent')],
                'indexes': [models.Index(fields=('state', 'expires_at'), name='replay_state_expiry_idx'), models.Index(fields=('station', 'station_session_id', 'aggregate_id'), name='replay_stream_idx'), models.Index(fields=('state', 'claimed_at'), name='replay_stale_claim_idx')],
            },
        ),
    ]
