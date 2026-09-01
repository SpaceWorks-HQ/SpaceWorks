from django.utils import timezone

from apps.accounts.models import User
from apps.backup.models import (
    ArchiveCustodyAlarmDelivery as Delivery,
    MakerspaceArchiveCustodyState as CustodyState,
)
from apps.integrations.models import EmailLog
from apps.makerspaces.models import Makerspace, MakerspaceMembership


def space(slug, state, *, modules=("notifications",)):
    makerspace = Makerspace.objects.create(
        name=slug,
        slug=slug,
        superadmin_access_enabled=(state == CustodyState.State.NOT_APPLICABLE),
        enabled_modules=list(modules),
    )
    CustodyState.objects.create(
        makerspace=makerspace,
        state=state,
        reason_code="" if state == CustodyState.State.NOT_APPLICABLE else "test",
        alarm_episode=0 if state == CustodyState.State.NOT_APPLICABLE else 1,
        alarm_revision=1,
        cleared_at=timezone.now() if state == CustodyState.State.NOT_APPLICABLE else None,
    )
    return makerspace


def manager(makerspace, suffix="manager", *, opted_in=True, email=True):
    user = User.objects.create_user(
        username=f"{makerspace.slug}-{suffix}",
        email=f"{makerspace.slug}-{suffix}@example.com" if email else "",
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=user,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        receives_notifications=opted_in,
    )
    return user


def operator(suffix="operator", *, email=True):
    return User.objects.create_user(
        username=suffix,
        email=f"{suffix}@example.com" if email else "",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
    )


def sent_dispatch(**kwargs):
    return EmailLog.objects.create(
        makerspace=kwargs["makerspace"],
        to_email=kwargs["to_email"],
        subject=kwargs["subject"],
        text_body=kwargs["text_body"],
        stream=kwargs["stream"],
        event=kwargs["event"],
        audience=kwargs["audience"],
        connection_kind=kwargs["connection"],
        status=EmailLog.Status.SENT,
        sent_at=timezone.now(),
    )


def channels(makerspace):
    return set(
        Delivery.objects.filter(makerspace=makerspace).values_list(
            "channel", flat=True
        )
    )
