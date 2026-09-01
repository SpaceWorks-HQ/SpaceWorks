"""Target-derived Part A and Lane D custody reconstruction."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit import services as audit
from apps.backup.custody import with_makerspace_custody_lock
from apps.backup.models import (
    ArchiveCustodyAlarmDelivery,
    ArchiveRecipientReservation,
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
    MakerspaceTenantExitCustodyState,
    TenantExitCustodyAlarmDelivery,
)
from apps.backup.recipients import (
    canonical_recipient,
    fingerprint_for,
    reissue_recipient_challenge,
    verify_recipient,
)
from apps.backup.tenant_exit_custody_alarms import required_intents_present_locked
from apps.makerspaces.models import Makerspace

from .target_state import IMPORTING
from .tenant_dump_errors import TenantDumpTargetError
from .tenant_dump_target_deks import decrypt_target_recipient_challenge


@dataclass(frozen=True)
class TargetCustodyReadiness:
    verified_recipient_count: int
    archive_state: str
    tenant_exit_state: str
    tenant_exit_alarm_revision: int


def assert_imported_part_a_operational_rows_absent(makerspace_id):
    """Prove deployment-local source custody rows did not travel in the dump."""
    recipients = MakerspaceArchiveRecipient.objects.filter(makerspace_id=makerspace_id)
    recipient_rows = tuple(recipients.order_by("pk"))
    fingerprints = tuple(row.fingerprint for row in recipient_rows)
    present = []
    if MakerspaceArchiveCustodyState.objects.filter(makerspace_id=makerspace_id).exists():
        present.append("archive custody state")
    if MakerspaceTenantExitCustodyState.objects.filter(
        makerspace_id=makerspace_id
    ).exists():
        present.append("tenant-exit custody state")
    if ArchiveCustodyAlarmDelivery.objects.filter(makerspace_id=makerspace_id).exists():
        present.append("archive custody outbox")
    if TenantExitCustodyAlarmDelivery.objects.filter(
        makerspace_id=makerspace_id
    ).exists():
        present.append("tenant-exit custody outbox")
    if ArchiveRecipientReservation.objects.filter(fingerprint__in=fingerprints).exists():
        present.append("recipient reservation")
    if present:
        _refuse(
            "The restored tenant contains deployment-operational custody rows: "
            + ", ".join(present)
            + ".",
            "source_custody_state_present",
        )
    for recipient in recipient_rows:
        _validate_carried_public_metadata(recipient)
        _require_source_proof_cleared(recipient)


def prove_imported_tenant_recipients(makerspace_id, identities, *, actor=None):
    """Challenge matching carried public rows and create target proof state."""
    makerspace = _target_makerspace(makerspace_id)
    identity_by_fingerprint = {
        identity.fingerprint: identity for identity in identities
    }
    if not identity_by_fingerprint:
        _refuse("No validated tenant identity is available.", "no_identity")
    recipients = tuple(
        MakerspaceArchiveRecipient.objects.filter(makerspace=makerspace).order_by("pk")
    )
    matching = {}
    for recipient in recipients:
        _validate_carried_public_metadata(recipient)
        identity = identity_by_fingerprint.get(recipient.fingerprint)
        if identity is None:
            continue
        if recipient.revoked_at is not None or recipient.compromised_at is not None:
            _refuse(
                "A frozen tenant identity maps to an ineligible carried recipient.",
                "recipient_ineligible",
            )
        if recipient.fingerprint in matching:
            _refuse("A carried tenant recipient is duplicated.", "recipient_duplicate")
        matching[recipient.fingerprint] = recipient
    _require_target_proof_provenance(recipients)
    if set(matching) != set(identity_by_fingerprint):
        _refuse(
            "The carried public-recipient rows do not match the supplied identities.",
            "recipient_set_mismatch",
        )

    proven = []
    for fingerprint in sorted(matching):
        recipient = matching[fingerprint]
        identity = identity_by_fingerprint[fingerprint]
        if _already_target_verified(recipient):
            proven.append(recipient.pk)
            continue
        _require_source_proof_cleared(recipient)
        recipient, challenge = reissue_recipient_challenge(
            recipient=recipient,
            actor=actor,
        )
        submitted_nonce = decrypt_target_recipient_challenge(identity, challenge)
        try:
            with transaction.atomic():
                recipient = verify_recipient(
                    recipient_id=recipient.pk,
                    makerspace_id=makerspace.pk,
                    submitted_nonce=submitted_nonce,
                    actor=actor,
                )
                audit.record(
                    actor,
                    "tenant_migration.target_archive_recipient_verified",
                    makerspace=makerspace,
                    target=recipient,
                    meta={
                        "fingerprint": recipient.fingerprint,
                        "proof_channel": "mounted_age_identity_challenge",
                    },
                )
        except ValidationError as exc:
            raise TenantDumpTargetError(
                "A target tenant recipient challenge failed.",
                code="recipient_challenge_failed",
            ) from exc
        proven.append(recipient.pk)
    reroute_target_custody(makerspace.pk)
    return tuple(proven)


def reroute_target_custody(makerspace_id):
    """Recompute states and decision-19b routing from current target authority."""
    with with_makerspace_custody_lock(makerspace_id):
        pass
    return target_custody_readiness(makerspace_id, recompute=False)


def target_custody_readiness(makerspace_id, *, recompute=True):
    """Fail closed for zero custody or a degraded revision without durable intents."""
    makerspace = _target_makerspace(makerspace_id)
    if recompute:
        with with_makerspace_custody_lock(makerspace.pk):
            pass
    archive_state = MakerspaceArchiveCustodyState.objects.get(
        makerspace=makerspace
    )
    tenant_exit_state = MakerspaceTenantExitCustodyState.objects.get(
        makerspace=makerspace
    )
    count = MakerspaceArchiveRecipient.objects.filter(
        makerspace=makerspace,
        verified_at__isnull=False,
        revoked_at__isnull=True,
        compromised_at__isnull=True,
    ).count()
    verified_rows = tuple(
        MakerspaceArchiveRecipient.objects.filter(
            makerspace=makerspace,
            verified_at__isnull=False,
            revoked_at__isnull=True,
            compromised_at__isnull=True,
        ).values_list("fingerprint", flat=True)
    )
    reserved = ArchiveRecipientReservation.objects.filter(
        fingerprint__in=verified_rows,
        makerspace_id_snapshot=makerspace.pk,
        kind=ArchiveRecipientReservation.Kind.TENANT,
    ).count()
    if reserved != count:
        _refuse(
            "Target recipient proof and reservation state diverge.",
            "recipient_reservation_state",
        )
    if archive_state.state != MakerspaceArchiveCustodyState.State.NOT_APPLICABLE:
        _refuse(
            "Target Part A custody must be not_applicable while superadmin access is enabled.",
            "archive_custody_forged",
        )
    if tenant_exit_state.state == MakerspaceTenantExitCustodyState.State.FLOOR_BREACHED_ZERO:
        _refuse("Target activation requires tenant-held custody.", "tenant_custody_zero")
    if count == 1 and (
        tenant_exit_state.state
        != MakerspaceTenantExitCustodyState.State.DEGRADED_ONE_RECIPIENT
        or tenant_exit_state.alarm_revision < 1
        or not required_intents_present_locked(tenant_exit_state)
    ):
        _refuse(
            "Degraded target custody lacks its durable decision-19b revision and intents.",
            "tenant_custody_degraded_unready",
        )
    if count >= 2 and tenant_exit_state.state != MakerspaceTenantExitCustodyState.State.HEALTHY:
        _refuse("Target tenant-exit custody state is inconsistent.", "tenant_custody_state")
    return TargetCustodyReadiness(
        verified_recipient_count=count,
        archive_state=archive_state.state,
        tenant_exit_state=tenant_exit_state.state,
        tenant_exit_alarm_revision=tenant_exit_state.alarm_revision,
    )


def _target_makerspace(makerspace_id):
    try:
        makerspace = Makerspace.objects.get(pk=makerspace_id)
    except Makerspace.DoesNotExist:
        _refuse("The preserved source makerspace does not exist on the target.", "target_missing")
    if makerspace.lifecycle_state != IMPORTING or not makerspace.superadmin_access_enabled:
        _refuse(
            "Recipient reconstruction requires an importing target with superadmin access.",
            "unsafe_target",
        )
    return makerspace


def _validate_carried_public_metadata(recipient):
    try:
        canonical = canonical_recipient(recipient.public_recipient)
    except ValidationError as exc:
        raise TenantDumpTargetError(
            "A carried tenant recipient is invalid.", code="recipient_metadata"
        ) from exc
    if (
        canonical != recipient.public_recipient
        or fingerprint_for(canonical) != recipient.fingerprint
    ):
        _refuse("A carried tenant recipient fingerprint is invalid.", "recipient_metadata")


def _require_source_proof_cleared(recipient):
    if (
        recipient.verified_at is not None
        or recipient.challenge_nonce_digest
        or recipient.challenge_issued_at is not None
    ):
        _refuse(
            "Imported recipient proof state was not cleared.",
            "source_recipient_proof_present",
        )


def _already_target_verified(recipient):
    if recipient.verified_at is None:
        return False
    return ArchiveRecipientReservation.objects.filter(
        fingerprint=recipient.fingerprint,
        makerspace_id_snapshot=recipient.makerspace_id,
        kind=ArchiveRecipientReservation.Kind.TENANT,
    ).exists()


def _require_target_proof_provenance(recipients):
    """Distinguish resumable target proof from forbidden carried proof state."""
    for recipient in recipients:
        reservation = ArchiveRecipientReservation.objects.filter(
            fingerprint=recipient.fingerprint
        ).first()
        if recipient.verified_at is None:
            if reservation is not None:
                _refuse(
                    "An unverified carried recipient already has a target reservation.",
                    "recipient_reservation_state",
                )
            _require_source_proof_cleared(recipient)
            continue
        if reservation is None or not _already_target_verified(recipient):
            _refuse(
                "Source recipient verification state cannot become target proof.",
                "source_recipient_proof_present",
            )


def _refuse(message, code):
    raise TenantDumpTargetError(message, code=code)
