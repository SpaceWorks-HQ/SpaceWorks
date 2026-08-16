from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces.archive_request_notifications import (
    schedule_created,
    schedule_resolved,
)
from apps.makerspaces.models import Makerspace, MakerspaceArchiveRequest
from apps.makerspaces.servability import is_servable

COOLDOWN = timedelta(hours=1)
DIRECT_ARCHIVE_NOTE = "Approved automatically because a superadmin archived the makerspace directly."
PENDING_CONSTRAINT = "uniq_pending_makerspace_archive_request"


class ArchiveRequestConflict(APIException):
    status_code = 409

    def __init__(self, detail, code):
        self.detail = {"detail": detail, "code": code}


class PendingArchiveRequestExists(ArchiveRequestConflict):
    def __init__(self):
        super().__init__(
            "A pending archive request already exists for this makerspace.",
            "pending_archive_request_exists",
        )


def create(makerspace, actor, reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Explain why this makerspace should be archived."})
    if len(reason) > 2000:
        raise ValidationError({"reason": "Ensure this field has no more than 2000 characters."})

    try:
        with transaction.atomic():
            locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
            _require_archive_authority(actor, locked)
            if not is_servable(locked):
                raise ArchiveRequestConflict(
                    "An unavailable makerspace cannot request archival.",
                    "makerspace_already_archived",
                )
            if not locked.superadmin_access_enabled:
                raise ArchiveRequestConflict(
                    "Enable superadmin access before requesting archival.",
                    "superadmin_access_disabled",
                )

            requests = list(
                MakerspaceArchiveRequest.objects.select_for_update()
                .filter(makerspace=locked)
                .order_by("-requested_at", "-pk")
            )
            if any(item.status == MakerspaceArchiveRequest.Status.PENDING for item in requests):
                raise PendingArchiveRequestExists()
            if requests and requests[0].requested_at > timezone.now() - COOLDOWN:
                # Without a per-space cooldown, managers can withdraw and immediately
                # recreate requests to fan governance mail out to every superadmin.
                raise ArchiveRequestConflict(
                    "Wait one hour after the previous archive request before creating another.",
                    "archive_request_cooldown",
                )

            archive_request = MakerspaceArchiveRequest.objects.create(
                makerspace=locked,
                requested_by=actor,
                reason=reason,
            )
            audit.record(
                actor,
                "makerspace.archive_requested",
                makerspace=locked,
                target=archive_request,
                meta={"archive_request_id": archive_request.pk},
            )
            schedule_created(archive_request.pk)
            return archive_request
    except IntegrityError as exc:
        if _constraint_name(exc) == PENDING_CONSTRAINT or PENDING_CONSTRAINT in str(exc):
            raise PendingArchiveRequestExists() from exc
        raise


def withdraw(archive_request, actor):
    with transaction.atomic():
        locked_space = Makerspace.objects.select_for_update().get(
            pk=archive_request.makerspace_id
        )
        _require_archive_authority(actor, locked_space)
        locked_request = _lock_request(archive_request.pk, locked_space.pk)
        _require_pending(locked_request)
        _resolve(
            locked_request,
            status=MakerspaceArchiveRequest.Status.WITHDRAWN,
            actor=actor,
            note="",
            resolved_at=timezone.now(),
        )
        audit.record(
            actor,
            "makerspace.archive_request_withdrawn",
            makerspace=locked_space,
            target=locked_request,
            meta={"archive_request_id": locked_request.pk},
        )
        # Authority here is the MANAGE_MAKERSPACE action, so a COLLEAGUE can withdraw a
        # request someone else filed. That person otherwise learns nothing: their request
        # simply disappears. Withdrawing your own request needs no mail -- you just did it.
        if locked_request.requested_by_id and locked_request.requested_by_id != getattr(
            actor, "pk", None
        ):
            schedule_resolved(locked_request.pk)
        return locked_request


def approve(archive_request, actor, resolution_note=""):
    note = _optional_note(resolution_note)
    with transaction.atomic():
        locked_space = Makerspace.objects.select_for_update().get(
            pk=archive_request.makerspace_id
        )
        locked_request = _lock_request(archive_request.pk, locked_space.pk)
        _require_pending(locked_request)
        resolved_at = timezone.now()
        from apps.makerspaces import lifecycle

        lifecycle._archive_locked(locked_space, actor, archived_at=resolved_at)
        _resolve(
            locked_request,
            status=MakerspaceArchiveRequest.Status.APPROVED,
            actor=actor,
            note=note,
            resolved_at=resolved_at,
        )
        audit.record(
            actor,
            "makerspace.archive_request_approved",
            makerspace=locked_space,
            target=locked_request,
            meta={"archive_request_id": locked_request.pk},
        )
        schedule_resolved(locked_request.pk)
        return locked_request


def decline(archive_request, actor, resolution_note):
    note = (resolution_note or "").strip()
    if not note:
        raise ValidationError({"resolution_note": "Explain why the request was declined."})
    if len(note) > 2000:
        raise ValidationError(
            {"resolution_note": "Ensure this field has no more than 2000 characters."}
        )
    with transaction.atomic():
        locked_space = Makerspace.objects.select_for_update().get(
            pk=archive_request.makerspace_id
        )
        locked_request = _lock_request(archive_request.pk, locked_space.pk)
        _require_pending(locked_request)
        _resolve(
            locked_request,
            status=MakerspaceArchiveRequest.Status.DECLINED,
            actor=actor,
            note=note,
            resolved_at=timezone.now(),
        )
        audit.record(
            actor,
            "makerspace.archive_request_declined",
            makerspace=locked_space,
            target=locked_request,
            meta={"archive_request_id": locked_request.pk},
        )
        schedule_resolved(locked_request.pk)
        return locked_request


def direct_archive(makerspace, actor):
    with transaction.atomic():
        locked_space = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        pending = (
            MakerspaceArchiveRequest.objects.select_for_update()
            .filter(
                makerspace=locked_space,
                status=MakerspaceArchiveRequest.Status.PENDING,
            )
            .first()
        )
        resolved_at = timezone.now()
        from apps.makerspaces import lifecycle

        lifecycle._archive_locked(locked_space, actor, archived_at=resolved_at)
        if pending is not None:
            _resolve(
                pending,
                status=MakerspaceArchiveRequest.Status.APPROVED,
                actor=actor,
                note=DIRECT_ARCHIVE_NOTE,
                resolved_at=resolved_at,
            )
            audit.record(
                actor,
                "makerspace.archive_request_approved",
                makerspace=locked_space,
                target=pending,
                meta={"archive_request_id": pending.pk, "automatic": True},
            )
            schedule_resolved(pending.pk)
        return locked_space


def _lock_request(request_id, makerspace_id):
    try:
        return MakerspaceArchiveRequest.objects.select_for_update().get(
            pk=request_id,
            makerspace_id=makerspace_id,
        )
    except MakerspaceArchiveRequest.DoesNotExist as exc:
        raise ArchiveRequestConflict(
            "Archive request does not belong to this makerspace.",
            "archive_request_not_found",
        ) from exc


def _require_pending(archive_request):
    if archive_request.status != MakerspaceArchiveRequest.Status.PENDING:
        raise ArchiveRequestConflict(
            "Only a pending archive request can make this transition.",
            "archive_request_not_pending",
        )


def _require_archive_authority(actor, makerspace):
    """Action-based, matching the views. `is_space_manager_identity` would be wrong here.

    That helper documents itself as deliberately NOT inferring identity from actions, so it
    refuses a custom role granted MANAGE_MAKERSPACE — and editable custom roles are the Part L
    architecture this project runs on. A space that rebuilt or renamed its administrator role
    would have been unable to file for its own archival. This gate is defence in depth behind
    the view's identical check; both must agree, or one of them is decorative.
    """
    if not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk):
        raise PermissionDenied("Managing archive requests requires MANAGE_MAKERSPACE.")


def _resolve(archive_request, *, status, actor, note, resolved_at):
    archive_request.status = status
    archive_request.resolved_by = actor
    archive_request.resolved_at = resolved_at
    archive_request.resolution_note = (note or "").strip()
    archive_request.save(
        update_fields=["status", "resolved_by", "resolved_at", "resolution_note"]
    )


def _constraint_name(exc):
    cause = getattr(exc, "__cause__", None)
    diag = getattr(cause, "diag", None)
    return getattr(diag, "constraint_name", None)


def _optional_note(value):
    note = (value or "").strip()
    if len(note) > 2000:
        raise ValidationError(
            {"resolution_note": "Ensure this field has no more than 2000 characters."}
        )
    return note
