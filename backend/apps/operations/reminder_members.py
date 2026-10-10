"""Shared scoped discovery and requester-only delivery for attendance reminders."""

from functools import reduce
from operator import or_

from datetime import timedelta, timezone as datetime_timezone

from django.db.models import CharField, Exists, OuterRef, Q, Value
from django.db.models.functions import Cast, Concat

from apps.accounts import rbac
from apps.integrations import recipients
from apps.integrations.email_templates import render
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.platform import module_enabled
from apps.operations.models_reminders import ReminderSchedule


def occurrence_subject(subject_id, starts_at):
    """A rescheduled start is a new occurrence; old committed claims stay closed."""
    return f"{subject_id}:{starts_at.astimezone(datetime_timezone.utc).isoformat()}"


def unfinished_subjects(queryset, makerspace, source, offsets, *, now, due_field="starts_at"):
    """Terminal schedules cannot occupy every batch and starve later members."""
    schedules = rbac.scope_for_scheduled_work(
        ReminderSchedule.objects.all(), makerspace_id=makerspace.pk,
    ).filter(source=source, due_at=OuterRef(due_field), kind="starts").filter(
        Q(subject=OuterRef("reminder_identity"))
        | Q(subject__startswith=Concat(OuterRef("reminder_identity"), Value(":"))),
    )
    queryset = queryset.annotate(reminder_identity=Cast("pk", output_field=CharField()))
    # A future second step must not keep the first batch occupied after its due
    # first step completed. Discover only subjects with unfinished steps due NOW;
    # schedule_reminders still seeds all their later offsets on first discovery.
    pending = [Q(**{f"{due_field}__lte": now - timedelta(seconds=offset)})
               & ~Exists(schedules.filter(offset_seconds=offset).exclude(
                   state=ReminderSchedule.State.PENDING,
               )) for offset in offsets]
    return queryset.filter(reduce(or_, pending)) if pending else queryset.none()


def recipient_member(makerspace, member_id, feature):
    if not member_id or not module_enabled(makerspace, "membership"):
        return None
    membership = rbac.scope_for_scheduled_work(
        MakerspaceMembership.objects.all(), makerspace_id=makerspace.pk,
    ).select_related("user").filter(
        user_id=member_id, status="active", receives_notifications=True,
        user__is_active=True, user__access_status="active",
    ).first()
    if membership is None or not membership.user.email:
        return None
    if recipients.has_selection(makerspace, feature, "reminder") and not recipients.requester_selected(
        makerspace, feature, "reminder",
    ):
        return None
    return membership.user


def dispatch_member_reminder(makerspace, *, feature, member, context, data):
    """Use matrix, template, email-module and quota delivery gates.

    A reminder names only its owner, so never fan it out to staff or chat rooms.
    Address is resolved from the live account, never supplied contact text.
    """
    template = render(makerspace, feature, "requester", "reminder", context)
    delivery = EmailDelivery(
        to_email=member.email, subject=template["subject"],
        text_body=template["text_body"], html_body=template["html_body"],
        audience="requester", stream=feature, mute_event="reminder", user_id=member.pk,
    )
    return notify_lifecycle(
        makerspace, feature=feature, event="reminder", sync=True,
        build=lambda: LifecyclePayload(
            text=template["text_body"], emails=(delivery,), context=context,
            data=data, staff_channels_enabled=False,
        ),
    )
