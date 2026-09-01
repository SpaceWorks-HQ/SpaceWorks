"""Makerspace archive and recovery lifecycle."""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit import services as audit
from apps.makerspaces.servability import is_servable


def archive_impact(makerspace):
    """Unsettled money that archiving this makerspace would make harder to reach."""
    from apps.payments.models import Payment

    owned_pending = Payment.objects.filter(
        makerspace=makerspace,
        status=Payment.Status.PENDING,
    ).count()
    routed_pending = Payment.objects.filter(
        via_makerspace=makerspace,
        status=Payment.Status.PENDING,
    ).exclude(makerspace=makerspace).count()
    return {
        "owned_pending": owned_pending,
        "routed_pending": routed_pending,
        "total_pending": owned_pending + routed_pending,
    }


def archive(makerspace, actor):
    from apps.makerspaces.archive_requests import direct_archive

    return direct_archive(makerspace, actor)


def _archive_locked(makerspace, actor, *, archived_at):
    if not makerspace.superadmin_access_enabled:
        raise ValidationError("Cannot archive a hidden makerspace.")
    if not is_servable(makerspace):
        raise ValidationError("Makerspace is not available for archival.")

    # This is an advisory snapshot: payment creation does not universally take
    # this lock, so a concurrent insert can change the count before commit.
    impact = archive_impact(makerspace)
    makerspace.archived_at = archived_at
    makerspace.archived_by = actor
    makerspace.public_inventory_enabled = False
    makerspace.save(
        update_fields=["archived_at", "archived_by", "public_inventory_enabled"]
    )
    audit.record(
        actor,
        "makerspace.archived",
        makerspace=makerspace,
        target=makerspace,
        meta=impact,
    )
    return makerspace


def unarchive(makerspace, actor):
    with transaction.atomic():
        locked = makerspace.__class__.objects.select_for_update().get(pk=makerspace.pk)
        if not locked.superadmin_access_enabled:
            raise ValidationError("Cannot unarchive a hidden makerspace.")
        if locked.archived_at is None:
            raise ValidationError("Makerspace is not archived.")
        from apps.tenant_migration.cutover import has_active_migrated_out_handoff

        if has_active_migrated_out_handoff(locked.pk):
            raise ValidationError(
                "A migrated-out makerspace can only be reopened with a signed abort receipt."
            )

        locked.archived_at = None
        locked.archived_by = None
        locked.save(update_fields=["archived_at", "archived_by"])
        audit.record(actor, "makerspace.unarchived", makerspace=locked, target=locked)
        return locked
